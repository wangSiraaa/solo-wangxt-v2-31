import { SimEvent } from './models';

/** 把后端 reason 码翻译成人话，解释该事件为何改变队列 / 坐席状态。 */
export function explainEvent(ev: SimEvent): { title: string; detail: string } {
  const qb = ev.queue_before?.length ?? 0;
  const qa = ev.queue_after?.length ?? 0;
  const delta = qa - qb;
  const d = delta > 0 ? `队列 +${delta}` : delta < 0 ? `队列 ${delta}` : '队列长度不变';

  switch (ev.type) {
    case 'SIM_START':
      return {
        title: '仿真开始',
        detail: `时钟 0 秒启动，计划来电 ${ev.planned_calls} 通（种子 ${ev.seed} 预生成），观测时长 ${ev.horizon_sec} 秒。`,
      };
    case 'SIM_END':
      return { title: '仿真结束', detail: `所有来电已在 ${ev.t_final?.toFixed(0)} 秒前得出结局（接通/放弃/过期）。` };
    case 'ARRIVAL':
      return {
        title: `来电进入排队：${ev.call_id}`,
        detail: `${ev.language}/${ev.skill}，优先级 ${ev.priority}，耐心 ${ev.patience_sec?.toFixed(0)} 秒、`
          + `通话预估 ${ev.talk_sec?.toFixed(0)} 秒。此刻没有能接的空闲坐席，故入队等待。${d}。`,
      };
    case 'ASSIGNED': {
      const via = (ev.overflow_rules_active?.length ?? 0) > 0
        ? `（经由溢出规则 #${ev.overflow_rules_active!.join(', #')} 才获得匹配坐席）`
        : '（基础技能直接匹配）';
      return {
        title: `接通：${ev.call_id} → ${ev.agent_id}`,
        detail: `等待 ${ev.wait_sec?.toFixed(1)} 秒后接通${via}；SLA 门槛 ${ev.sla_sec} 秒，`
          + `${ev.met_sla ? '✅ 达标' : '❌ 超时'}。派发器在事件前快照中确认该坐席为 AVAILABLE，`
          + `接通瞬间置为 ON_CALL。${d}。`,
      };
    }
    case 'CALL_END':
      return {
        title: `通话结束：${ev.call_id}`,
        detail: `${ev.agent_id} 的通话持续 ${ev.talk_sec?.toFixed(0)} 秒结束，随后进入话后整理。`,
      };
    case 'WRAP_START':
      return {
        title: `整理开始：${ev.agent_id}`,
        detail: `话后整理 ${ev.wrap_sec} 秒，期间状态 WRAP，不能接新来电——这是队列继续等待的原因之一。`,
      };
    case 'WRAP_END':
      return {
        title: `整理结束：${ev.agent_id}`,
        detail: `坐席恢复 AVAILABLE，派发器立即重新扫描等待队列。${d}。`,
      };
    case 'ABANDONED':
      return {
        title: `客户放弃：${ev.call_id}`,
        detail: `等待 ${ev.waited_sec?.toFixed(1)} 秒达到耐心上限 ${ev.patience_sec?.toFixed(0)} 秒，挂断离队。`
          + (ev.overflow_rules_active?.length
            ? `（虽已触发溢出 #${ev.overflow_rules_active.join(', #')}，仍无坐席可接）`
            : '（始终未获得匹配坐席）')
          + ` ${d}。`,
      };
    case 'OVERFLOW':
      return {
        title: `溢出规则 #${ev.rule_index} 生效：${ev.call_id}`,
        detail: `已等待 ${ev.waited_sec?.toFixed(1)} 秒 ≥ 阈值 ${ev.threshold_sec} 秒，`
          + `新增可接坐席能力：${ev.added_capabilities?.map(c => `${c.language}/${c.skill}`).join('、')}。`
          + `${ev.note ?? ''} 派发器立即重扫队列。${d}。`,
      };
    case 'EXPIRED':
      return {
        title: `观测截止未接通：${ev.call_id}`,
        detail: `${ev.waited_sec?.toFixed(1)} 秒后到达场景观测终点，仍在排队，计为 EXPIRED（不计入放弃）。${d}。`,
      };
    case 'SHIFT_START':
      return {
        title: `坐席上班：${ev.agent_id}`,
        detail: `按排班登录，状态 OFFLINE → AVAILABLE，派发器立即尝试消化队列。${d}。`,
      };
    case 'SHIFT_END':
      return {
        title: `坐席下班：${ev.agent_id}`,
        detail: ev.reason === 'scheduled_logout'
          ? '到点时为空闲，立即 OFFLINE。'
          : '到点时仍在通话/整理中，已挂起下班；此刻整理结束才真正 OFFLINE。',
      };
    case 'SHIFT_END_PENDING':
      return {
        title: `到点但未下班：${ev.agent_id}`,
        detail: `排班已到点，坐席正忙于 ${ev.current_call}（通话或整理）。不会强行挂断，`
          + `设为延迟下班，等本次服务结束再登出——交接窗口队列可能因此积压。`,
      };
    default:
      return { title: ev.type, detail: ev.reason };
  }
}

export const EVENT_COLORS: Record<string, string> = {
  ARRIVAL: '#4f8cff',
  ASSIGNED: '#2faa6a',
  CALL_END: '#8a8f98',
  WRAP_START: '#d99a2b',
  WRAP_END: '#c7a86b',
  ABANDONED: '#e0524d',
  OVERFLOW: '#9b5de5',
  EXPIRED: '#777',
  SHIFT_START: '#1f9d8c',
  SHIFT_END: '#555',
  SHIFT_END_PENDING: '#e07b39',
  SIM_START: '#333',
  SIM_END: '#333',
};
