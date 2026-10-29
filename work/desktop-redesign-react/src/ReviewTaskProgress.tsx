import {Progress} from 'antd';
import type {Task} from './review-data';
export default function TaskProgress({task,compact=false}:{task:Task;compact?:boolean}){
 const percent=task.total?Math.min(100,Math.floor(task.done/task.total*100)):0;
 const paused=task.state==='已暂停',waiting=task.state==='等待归档',failed=task.state==='请求失败',gap=task.state==='来源缺口';
 return <div className={compact?'tree-progress':'task-progress-summary'} aria-label={`${task.name}采集进度`}><div><span>{paused?'未启动':`${task.done.toLocaleString()} / ${task.total.toLocaleString()}`}</span><span>{paused?'已暂停':waiting?'待归档':failed?'已中断':gap?'有缺口':task.state==='已核验'?'已核验':`${percent}%`}</span></div>{!paused&&<Progress percent={percent} showInfo={false} size="small" status={failed?'exception':'normal'} strokeColor={waiting||gap?'#faad14':task.state==='已核验'?'#52c41a':undefined}/>}</div>;
}
