"""Opt-in, read-only method decisions; sources remain development candidates."""
from __future__ import annotations

import re
import streamlit as st

from .storage import content_hash
from .workflow_inputs_ui import _text, render_workflow_review
from .workflow_methods import configured_method_service


_STATUS = {'reported_met': '报告符合', 'reported_unmet': '报告不符合',
    'needs_information': '信息不足', 'not_applicable': '此规则未触发',
    'option_not_applicable': '该选项不适用；不据此否定整个方法', 'advisory': '需保留的取舍'}
_DECISION = {'conditional_plan': '仅保留条件计划', 'blocked': '当前报告阻塞此配置',
    'needs_information': '需补充信息', 'needs_clarification': '报告冲突，先澄清'}


def _used_fields(routes, scope):
    ids = set()
    for route in routes:
        rules = route['rules'] if scope == 'method' else route['local_policy_checks']
        for rule in rules:
            for expr in (rule.get('when'), rule.get('expect')):
                if expr:
                    for atom in expr['atoms']:
                        ids.add(atom['field_id'])
                        if atom['other_field'] is not None:
                            ids.add(atom['other_field'])
    return ids


def _fields(fields, used, scope, prefix):
    # A conditional widget remains reachable even when its controller is not
    # itself referenced by a scientific rule. The schema permits one level.
    used = set(used)
    used.update(field['show_when']['field_id'] for field in fields
        if field['field_id'] in used and field['show_when'] is not None)
    values, valid = {}, True
    for field in sorted(fields, key=lambda f: f['show_when'] is not None):
        if field['scope'] != scope or field['field_id'] not in used:
            continue
        when = field['show_when']
        if when is not None and values.get(when['field_id']) != when['value']:
            continue
        key = prefix + scope + '_' + field['field_id']
        if field['kind'] == 'integer':
            raw = st.text_input(field['label'], key=key, help='留空表示未知；填非负整数，不从原始基因轴猜测过滤后的数量。')
            if not raw:
                values[field['field_id']] = None
            elif re.fullmatch(r'[0-9]{1,8}', raw) and int(raw) <= 10_000_000:
                values[field['field_id']] = int(raw)
            else:
                st.error('数值需为0至10000000的整数；未执行检查。')
                valid = False
        elif field['kind'] == 'boolean':
            values[field['field_id']] = st.selectbox(field['label'], [None, False, True],
                format_func=lambda v: {None: '未说明', False: '否', True: '是'}[v], key=key)
        else:
            values[field['field_id']] = st.selectbox(field['label'], [None, *field['choices']],
                format_func=lambda v: '未说明' if v is None else v, key=key)
    return values, valid


def render_workflow_methods(ledger):
    if ledger.get_state('workflow_method_catalog') is None:
        return
    st.subheader('开发候选方法 · 配置与适用条件')
    st.caption('填写明确已知的信息。这里只核对用户报告和来源条件，不测量数据、不授权执行。')
    try:
        service = configured_method_service(ledger)
        catalog = service.catalog
        base = {r['route_id']: r for r in service.inputs.catalog['routes']}
        routes = {r['route_id']: r for r in catalog['routes']}
        prefix = 'workflow_methods_' + content_hash({'workspace': str(ledger.workspace.root),
            'catalog_hash': service.catalog_hash})[:20] + '_'
        chosen = st.multiselect('比较的方法', list(routes), default=list(routes)[:1],
            max_selections=4, format_func=lambda r: base[r]['label'], key=prefix + 'routes')
        if not chosen:
            return
        # Recheck provenance/governance on every render, including refreshes.
        # This is a pure read, not a new model turn, fit or saved assessment.
        context = service.evaluate(chosen, {})
    except (ValueError, KeyError, TypeError, RuntimeError):
        st.error('方法预览不可用；来源或目录未通过检查，没有调用模型或执行分析。')
        return
    inputs = {}
    for route_id in chosen:
        for requirement in base[route_id]['requirements']:
            key = requirement['report_pointer'].removeprefix('/reported_inputs/')
            if key not in inputs:
                inputs[key] = st.selectbox(requirement['label'], [None, False, True],
                    format_func=lambda v: {None: '未说明', False: '报告不符合', True: '报告符合'}[v],
                    key=prefix + 'input_' + key)
    selected = [routes[r] for r in chosen]
    st.caption('方法配置：选项未启用时，不追问该选项的后续参数。')
    config, valid = _fields(catalog['fields'], _used_fields(selected, 'method'), 'method', prefix)
    enabled = (st.checkbox('同时核对固定实验协议（仍为用户报告）', key=prefix + 'protocol')
        if any(r['local_policy_checks'] for r in selected) else False)
    protocol, protocol_valid = (_fields(catalog['fields'], _used_fields(selected, 'protocol'), 'protocol', prefix)
        if enabled else ({}, True))
    profile = {'reported_inputs': inputs, 'reported_config': config, 'reported_protocol': protocol}
    fingerprint = content_hash({'profile': profile, 'routes': chosen, 'protocol_selected': enabled,
        'catalog_hash': service.catalog_hash, 'source_context': context,
        'governance_version': ledger.get_state('governance_version', 0)})
    result_key = prefix + 'result'
    if not valid or not protocol_valid:
        st.session_state.pop(result_key, None)
        return
    if st.button('检查方法配置', key=prefix + 'evaluate'):
        try:
            result = service.evaluate(chosen, profile, include_local_protocol=enabled)
            st.session_state[result_key] = {'fingerprint': fingerprint, 'result': result}
        except (ValueError, KeyError, TypeError, RuntimeError):
            st.session_state.pop(result_key, None)
            st.error('方法配置检查未完成；没有创建任务或保存审核。')
    saved = st.session_state.get(result_key)
    if not saved:
        return
    if saved['fingerprint'] != fingerprint:
        st.info('输入、方法、目录或治理状态已改变，旧结果已隐藏。')
        return
    result = saved['result']
    for route in result['route_results']:
        with st.container(border=True):
            _text(route['label'] + '：' + _DECISION[route['method_decision']])
            _text('方法范围：' + route['method_scope'])
            _text('来源版本范围（不是当前环境版本测量）：' + route['version_scope'])
            for rule in route['configuration_checks']:
                _text(rule['label'] + '：' + _STATUS[rule['status']])
                for binding in rule['source_bindings']:
                    _text(binding['attribute']['value'])
                    for qualifier in binding['attribute']['qualifiers']:
                        _text('来源限定：' + qualifier)
            if route['report_conflicts']:
                st.warning('输入声明与配置报告冲突；保留两者，请先澄清。')
                st.json(route['report_conflicts'])
            _text('本机执行未绑定、未授权、未执行；完整科学适用性尚未建立。')
            with st.expander('原输入检查与完整来源'):
                render_workflow_review({'route_results': [route['input_review']],
                    'catalog_hash': result['base_catalog_hash'], 'profile_hash': result['profile_hash'],
                    'result_hash': result['result_hash']})
                for source in route['input_review']['source_records']:
                    for attr in source['claim']['typed_attributes']:
                        _text(attr['name'] + '：' + attr['value'])
                        for qualifier in attr['qualifiers']:
                            _text('该属性的来源限定：' + qualifier)
            with st.expander('独立实验协议与技术记录'):
                _text('研究者协议检查：' + route['local_protocol']['state'])
                st.json(route['local_protocol'])
                st.json({'catalog_hash': result['catalog_hash'], 'result_hash': result['result_hash'],
                    'protocol': result['separate_local_protocol'], 'profile': result['input_profile']})
