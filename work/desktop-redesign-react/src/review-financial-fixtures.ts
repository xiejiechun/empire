import {statement} from './review-data';
import type {StatementRow} from './review-data';
const make=(rows:[string,number|null,boolean?][],balance=false):StatementRow[]=>rows.map(([label,v,group],i)=>({id:String(i),label,group,indent:!group,values:(balance?[1,.98,.95,.93,.91,.90]:[1,.47,1.8,1.25,.92,.43]).map(f=>v===null?null:Math.round(v*f*100)/100)}));
export const reports:Record<string,StatementRow[]>={income:statement,balance:make([
 ['资产总计',5800,true],['流动资产合计',3200],['货币资金',900],['应收账款',600],['存货',850],['其他流动资产',850],['非流动资产合计',2600],['固定资产',1800],['无形资产',400],['其他非流动资产',400],['负债合计',2900,true],['流动负债',1700],['非流动负债',1200],['所有者权益合计',2900,true],['归属于母公司所有者权益',2700],['少数股东权益',200],['其他权益工具',null]
 ],true),cashflow:make([
 ['经营活动产生的现金流量净额',340,true],['销售商品、提供劳务收到的现金',2800],['收到其他与经营活动有关的现金',100],['经营活动现金流入小计',2900],['购买商品、接受劳务支付的现金',2100],['支付给职工以及为职工支付的现金',260],['支付的各项税费',200],['经营活动现金流出小计',2560],['投资活动产生的现金流量净额',-180,true],['投资活动现金流入小计',120],['投资活动现金流出小计',300],['筹资活动产生的现金流量净额',-90,true],['筹资活动现金流入小计',200],['筹资活动现金流出小计',290],['汇率变动对现金的影响',2],['现金及现金等价物净增加额',72,true],['期初现金及现金等价物余额',828],['期末现金及现金等价物余额',900]
 ])};
export const reportNames:Record<string,string>={income:'利润表',balance:'资产负债表',cashflow:'现金流量表'};
