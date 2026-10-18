"""One explicit final-format regeneration, never a gateway or semantic retry."""
from __future__ import annotations

from copy import deepcopy
import json
import math

from jsonschema import Draft202012Validator

from .evidence_answers import _payload
from .model_capabilities import wire_receipt_matches
from .model_service import ModelCallError, _strict_json, local_validation_matches
from .storage import canonical_json, content_hash


FINAL_FORMAT_REPAIR_POLICY = 'final_format_once_v1'
FORMAT_REPAIR_RUN_VERSION = 'development-workflow-chat-format-repair-v1'
FORMAT_REPAIR_RESERVATION_KIND = 'workflow_format_repair_reservation'
FORMAT_REPAIR_INSTRUCTIONS = """\n本轮显式repair_policy=final_format_once_v1：在已有成功只读检查后，若最终输出仅有可绑定的已知结构错误，应用最多在原三次请求额度内要求一次完整finish重生成。坏输出不成为动作或证据；不能修复初次检查、语义或工具错误。所有原合同、来源、P/E、输入状态和执行限制保持不变。"""
_STATIC_FEEDBACK = '上次最终输出未通过本地结构合同。请仅依据已有完整原话与工具/来源上下文，重新生成一个完整finish；修正所列结构约束。不得执行工具、续写坏输出或改变事实、来源、状态与缺口规则。'
_FIELDS = frozenset({'action','route_ids','reports','answer','d','s','p','m','i','f','a','e','k','r','t'})
_VALIDATORS = frozenset({'maxLength','minLength','maxItems','minItems','uniqueItems',
    'required','additionalProperties','type','pattern','enum','const'})


class FormatRepairError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise FormatRepairError(code)


def known_usage(receipt):
    counts = [(receipt.get('usage') or {}).get(k) for k in ('input_tokens','output_tokens')]
    return receipt.get('usage_known') is True and all(type(v) is int and v >= 0 for v in counts)


def record_account(receipt, budget):
    counts = [(receipt.get('usage') or {}).get(k) for k in ('input_tokens','output_tokens')]
    tokens = sum(counts) if known_usage(receipt) else (
        budget['max_input_tokens'] + budget['max_output_tokens'])
    cost = receipt.get('cost_usd')
    known = (known_usage(receipt) and receipt.get('cost_known') is True and type(cost) in (int,float)
        and math.isfinite(cost) and cost >= 0)
    return tokens, cost if known else 0.0, known


def full_request_proxy(profile, messages, response_format, budget, validation_format=None):
    payload = _payload(profile,messages,response_format,budget,validation_format)
    return len(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()) + 256


def admit_request(profile, messages, response_format, budget, *, validation_format=None,
                  proxy_used=0, proxy_cap, cost_known=True):
    proxy = full_request_proxy(profile,messages,response_format,budget,validation_format)
    require(proxy <= budget['max_input_tokens'], 'repair_input_capacity_exceeded')
    require(proxy_used + proxy + budget['max_output_tokens'] <= proxy_cap, 'repair_total_proxy_exceeded')
    cap = budget.get('max_cost_usd')
    if cap is not None:
        rates = [profile.get(k) for k in ('input_usd_per_million','output_usd_per_million')]
        require(cost_known and all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in rates),
            'repair_cost_unknown')
        require(cap > 0 and (budget['max_input_tokens']*rates[0] + budget['max_output_tokens']*rates[1])/1_000_000 <= cap,
            'repair_remaining_cost_insufficient')
    else:
        require(all(profile.get(k) is not None for k in ('input_usd_per_million','output_usd_per_million'))
            or budget.get('allow_unknown_cost') is True, 'repair_unknown_cost_not_allowed')
    return proxy


def _diagnostics(structured, final_format):
    errors = list(Draft202012Validator(final_format['json_schema']['schema']).iter_errors(structured))
    require(bool(errors), 'rejected_output_now_valid')
    result = []
    for error in errors:
        path = list(error.absolute_path)
        require(error.validator in _VALIDATORS and not error.context, 'unsupported_format_error')
        require(all((type(v) is int and 0 <= v < 10000) or (type(v) is str and v in _FIELDS) for v in path),
            'unsupported_format_path')
        item = {'path':'/'+'/'.join(map(str,path)), 'validator':error.validator}
        if error.validator in {'maxLength','minLength','maxItems','minItems'}:
            require(type(error.validator_value) is int and error.validator_value >= 0, 'invalid_schema_limit')
            item['limit'] = error.validator_value
            require(isinstance(error.instance,(str,list)), 'invalid_length_instance')
            item['actual_length'] = len(error.instance)
        result.append(item)
    result.sort(key=lambda v:(v['path'],v['validator']))
    feedback = {'schema_version':'workflow-safe-final-format-feedback-v1', 'diagnostics':result[:4],
        'additional_diagnostic_count':max(0,len(result)-4)}
    require(len(canonical_json(feedback).encode()) <= 1024, 'format_feedback_capacity_exceeded')
    return feedback


def bind_invalid_final(ledger, profile, error, messages, response_format, budget, *,
                       validation_format, final_format, baseline_call):
    """Bind an actual invalid output without relaxing the success-only binder."""
    require(isinstance(error,ModelCallError) and error.outcome == 'invalid_response', 'not_known_format_failure')
    receipt = error.receipt
    require(isinstance(receipt,dict) and isinstance(error.call_id,str) and error.call_id, 'missing_failed_receipt')
    call_id = error.call_id
    request = ledger.get_record('model_request',call_id)
    output = ledger.get_record('model_output',call_id)
    expected = _payload(profile,messages,response_format,budget,validation_format)
    admitted = (len(json.dumps(expected,ensure_ascii=False,allow_nan=False).encode()) + 256
        if validation_format is not None else len(json.dumps(
            {'messages':messages,'response_format':response_format},ensure_ascii=False).encode()) + 256)
    require(receipt == ledger.get_record('model_call',call_id) and receipt.get('call_id') == call_id
        and receipt.get('status') == 'invalid_response' and receipt.get('finish_reason') == 'stop'
        and receipt.get('budget_exceeded') is False and known_usage(receipt)
        and receipt.get('input_estimate_method') == 'utf8_bytes_plus_256_not_tokenizer'
        and receipt.get('estimated_input_tokens') == admitted, 'failed_receipt_not_eligible')
    require(receipt.get('profile_id') == profile['id'] and receipt.get('budget') == budget
        and receipt.get('connection_id') == profile['connection_id']
        and receipt.get('requested_model') == profile['model']
        and ledger.get_record('model_profile',profile['id']) == profile
        and baseline_call.get('profile_hash') == content_hash(profile)
        and baseline_call['receipt'].get('profile_id') == profile['id']
        and baseline_call['receipt'].get('requested_model') == profile['model']
        and isinstance(receipt.get('returned_model'),str) and bool(receipt['returned_model'])
        and receipt['returned_model'] == baseline_call['receipt'].get('returned_model'), 'format_repair_model_binding_changed')
    require(request and request.get('id') == call_id and request.get('payload') == expected
        and request.get('request_hash') == content_hash(expected)
        and wire_receipt_matches(profile,receipt,response_format)
        and local_validation_matches(request,receipt,validation_format), 'failed_request_binding_changed')
    require(output and output.get('id') == call_id and type(output.get('text')) is str
        and output.get('text_hash') == content_hash(output['text'])
        and receipt.get('raw_output_record_hash') == content_hash(output)
        and output.get('finish_reason') == 'stop', 'failed_raw_output_binding_changed')
    try:
        structured = _strict_json(output['text'])
    except (TypeError,ValueError):
        raise FormatRepairError('strict_json_failure_not_repairable') from None
    require(type(structured) is dict and set(structured) == {'action','route_ids','reports','answer'}
        and structured.get('action') == 'finish' and structured.get('route_ids') == []
        and structured.get('reports') == [] and type(structured.get('answer')) is dict
        and {'d','s','p','m'}.issubset(structured['answer']), 'not_complete_final_intent')
    canonical = validation_format or response_format
    require(canonical.get('type') == 'json_schema' and bool(list(Draft202012Validator(
        canonical['json_schema']['schema']).iter_errors(structured))), 'original_output_not_canonical_invalid')
    feedback = _diagnostics(structured,final_format)
    feedback.update(failed_call_id=call_id, failed_raw_output_record_hash=content_hash(output),
        request_hash=request['request_hash'], final_format_hash=content_hash(final_format))
    require(len(canonical_json(feedback).encode()) <= 1024, 'format_feedback_capacity_exceeded')
    return {'receipt':deepcopy(receipt),'request_hash':request['request_hash'],
        'raw_output_record_hash':content_hash(output),'feedback':feedback}


def repair_messages(messages, feedback):
    require(len(canonical_json(feedback).encode()) <= 1024, 'format_feedback_capacity_exceeded')
    return [*deepcopy(messages), {'role':'user','content':_STATIC_FEEDBACK+'\n'+canonical_json(feedback)}]


def capacity_repair_messages(messages):
    """Conservative escaped 1024-byte envelope; sizing only, never a receipt."""
    feedback = {'schema_version':'synthetic-repair-capacity-only','padding':''}
    while len(canonical_json({**feedback,'padding':feedback['padding']+'\\'}).encode()) <= 1024:
        feedback['padding'] += '\\'
    return repair_messages(messages,feedback)


def reserve_once(ledger, request, payload, *, execution_guard=None):
    """Owner check, explicit absence and reservation share BEGIN IMMEDIATE."""
    with ledger.transaction() as tx:
        if execution_guard is not None:
            execution_guard(tx,None)
        require(ledger.get_record(FORMAT_REPAIR_RESERVATION_KIND,request['id'],conn=tx) is None,
            'format_repair_already_reserved')
        ledger.put_record(FORMAT_REPAIR_RESERVATION_KIND,request['id'],payload,conn=tx)
    return deepcopy(payload)


def validate_repaired_turn(ledger, models, request, turn, prepared):
    """Read-only replay of every actual attempt, including the rejected one."""
    from .workflow_chat import WorkflowChatAdapter
    run = turn.get('workflow_run') or {}
    require(request['workflow_options'].get('repair_policy') == FINAL_FORMAT_REPAIR_POLICY
        and prepared['workflow_material'].get('repair_policy') == FINAL_FORMAT_REPAIR_POLICY
        and run.get('repair_policy') == FINAL_FORMAT_REPAIR_POLICY
        and run.get('schema_version') == FORMAT_REPAIR_RUN_VERSION
        and run.get('binding_hash') == content_hash({k:v for k,v in run.items() if k != 'binding_hash'})
        and run.get('turn_id') == request['id'] and run.get('request_hash') == request['request_hash']
        and run.get('prepared_hash') == content_hash(prepared), 'repair_run_binding_changed')
    attempts, accepted = run.get('attempts'), run.get('calls')
    require(isinstance(attempts,list) and 2 <= len(attempts) <= 3 and isinstance(accepted,list),
        'repair_attempt_trace_incomplete')
    require([a.get('attempt_index') for a in attempts] == list(range(len(attempts)))
        and all(isinstance(a.get('call_id'),str) and a['call_id'] for a in attempts)
        and len({a['call_id'] for a in attempts}) == len(attempts), 'repair_attempt_order_changed')
    adapter = WorkflowChatAdapter(ledger,models,request,prepared)
    messages, steps, text, used = deepcopy(prepared['messages']), [], None, set()
    receipts, tokens, total_cost, cost_known, proxy_used = [], 0, 0.0, True, 0
    cap = 3*(request['budget']['max_input_tokens']+request['budget']['max_output_tokens'])
    for index, attempt in enumerate(attempts):
        adapter.check()
        final_only = index == 2 or len(steps) == 2 or adapter.repair_reservation is not None
        fmt, local = adapter.format(final_only), adapter.validation_format(final_only)
        budget = deepcopy(request['budget'])
        if budget.get('max_cost_usd') is not None:
            require(cost_known and total_cost < budget['max_cost_usd'], 'repair_cost_projection_changed')
            budget['max_cost_usd'] -= total_cost
        profile = ledger.get_record('model_profile',request['profile_id'])
        proxy = admit_request(profile,messages,fmt,budget,validation_format=local,
            proxy_used=proxy_used,proxy_cap=cap,cost_known=cost_known)
        receipt = ledger.get_record('model_call',attempt['call_id'])
        require(receipt and receipt == attempt.get('receipt') and attempt.get('budget') == budget
            and attempt.get('profile_hash') == content_hash(profile) and known_usage(receipt)
            and receipt.get('budget_exceeded') is False, 'repair_actual_receipt_changed')
        receipts.append(receipt)
        charged, cost, known = record_account(receipt,budget)
        tokens += charged; total_cost += cost; cost_known = cost_known and known
        proxy_used += proxy + budget['max_output_tokens']
        outcome = attempt.get('outcome')
        if outcome == 'known_format_rejected':
            require(index < len(attempts)-1 and adapter.repair_reservation is None
                and attempts[index+1].get('repair_of_call_id') == attempt['call_id'], 'repair_transition_changed')
            adapter.record_attempt(receipt,messages,fmt,budget,attempt_index=index,final_only=final_only,
                full_input_proxy=proxy,outcome='terminal_failure')
            next_budget = deepcopy(request['budget'])
            if next_budget.get('max_cost_usd') is not None:
                next_budget['max_cost_usd'] -= total_cost
            error = ModelCallError('retained known format rejection',call_id=attempt['call_id'],
                receipt=receipt,outcome='invalid_response')
            messages,reservation = adapter.plan_repair(error,messages,fmt,budget,next_budget=next_budget,
                proxy_used=proxy_used,proxy_cap=cap,cost_known=cost_known)
            require(reservation == run.get('repair_reservation') == ledger.get_record(
                FORMAT_REPAIR_RESERVATION_KIND,request['id']), 'repair_reservation_changed')
            adapter.repair_reservation = deepcopy(reservation)
            adapter.attempts[-1]['outcome'] = 'known_format_rejected'
        else:
            require(outcome == 'accepted_action', 'nonusable_attempt_in_succeeded_repair_run')
            matches = [c for c in accepted if c.get('call_id') == attempt['call_id']]
            require(len(matches) == 1 and attempt['call_id'] not in used
                and matches[0].get('attempt_index') == index, 'repair_accepted_call_changed')
            used.add(attempt['call_id'])
            action = adapter.accept({**receipt,'structured':matches[0]['wire']},messages,fmt,budget,
                attempt_index=index,final_only=final_only,full_input_proxy=proxy)
            if action['action'] == 'finish':
                require(index == len(attempts)-1, 'repair_continued_after_finish')
                text = adapter.finish(action)
            else:
                require(adapter.repair_reservation is None, 'repair_must_not_evaluate')
                result = adapter.tool(action,receipt)
                steps.append({'index':index,'action':action['action'],'result':result})
                messages = adapter.messages_after_tool(action,result)
        require(adapter.attempts[-1] == attempt, 'repair_attempt_projection_changed')
    require(len(used) == len(accepted) and text is not None and text == turn.get('answer')
        and adapter.output_fields()['workflow_run'] == run, 'repair_final_projection_changed')
    actual_steps = turn.get('agent_steps',[])
    require(len(actual_steps) == len(steps) and all(all(a.get(k) == b[k] for k in b)
        for a,b in zip(actual_steps,steps)), 'repair_tool_steps_changed')
    for key in ('workflow_review','workflow_interpretations','workflow_answer'):
        require(turn.get(key) == adapter.output_fields()[key], 'repair_saved_projection_changed')
    require(adapter.repair_reservation is not None or ledger.get_record(
        FORMAT_REPAIR_RESERVATION_KIND,request['id']) is None, 'unexpected_repair_reservation')
    expected = {'max_model_calls':3,'model_calls':len(receipts),'max_tool_steps':2,
        'max_total_token_reservation':cap,'charged_or_reserved_tokens':tokens,
        'cost_known':cost_known,'cost_usd':total_cost if cost_known else None,
        'max_cost_usd':request['budget'].get('max_cost_usd'),
        'input_proxy_plus_output_reservations':proxy_used}
    require(turn.get('receipts') == receipts and turn.get('receipt') == receipts[-1]
        and turn.get('agent_budget') == expected and turn.get('analysis_task_ids') == []
        and turn.get('referenced_analysis_task_ids') == [] and turn.get('result_bindings') == [],
        'repair_all_attempt_budget_changed')
    return adapter.output_fields()
