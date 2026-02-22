const riskLabelMap: Record<string, string> = {
  credible: '可信',
  suspicious: '可疑',
  high_risk: '高风险',
  needs_context: '需要补充语境',
  likely_misinformation: '疑似不实信息',
};

const riskLevelMap: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
};

const stanceMap: Record<string, string> = {
  support: '支持',
  refute: '反驳',
  insufficient: '证据不足',
  doubt: '质疑',
  mixed: '混合',
  neutral: '中立',
};

const scenarioMap: Record<string, string> = {
  general: '通用',
  health: '医疗健康',
  governance: '政务治理',
  security: '公共安全',
  media: '媒体传播',
  technology: '科技产业',
  education: '教育校园',
};

const domainMap: Record<string, string> = {
  health: '医疗健康',
  governance: '政务治理',
  security: '公共安全',
  media: '媒体传播',
  technology: '科技产业',
  education: '教育校园',
  general: '通用',
};

const sourceTypeMap: Record<string, string> = {
  local_kb: '本地知识库',
  web_live: '联网检索',
  web_summary: '联网聚合',
};

const emotionMap: Record<string, string> = {
  anger: '愤怒',
  fear: '恐惧',
  sadness: '悲伤',
  surprise: '惊讶',
  neutral: '中性',
  joy: '喜悦',
  disgust: '厌恶',
  anticipation: '期待',
  trust: '信任',
};

const simulationStanceMap: Record<string, string> = {
  supportive: '支持',
  opposing: '反对',
  neutral: '中立',
  skeptical: '质疑',
  mixed: '混合',
  dismissive: '否定',
  curious: '好奇',
};

const englishReasonMap: Array<[RegExp, string]> = [
  [/Matched risk keyword:/i, '命中高风险词：'],
  [/Matched trust keyword:/i, '命中可信线索词：'],
  [/Contains a traceable link/i, '包含可追溯链接'],
  [/No strong risk\/trust signal found, manual review suggested/i, '未发现明显风险或可信信号，建议人工复核'],
  [/No evidence found for/i, '未找到可用证据：'],
  [/is contradicted by evidence/i, '被证据反驳'],
  [/lacks decisive support/i, '证据不足以形成明确支持'],
  [/Need manual verification/i, '需要人工复核'],
  [/Primary stance:/i, '主立场：'],
  [/Evidence count:/i, '证据数量：'],
  [/Alignment:/i, '对齐结论：'],
];

const englishSimulationMap: Array<[RegExp, string]> = [
  [/Rapid spread via emotional reposts/i, '情绪化转发导致快速扩散'],
  [/Counter narrative from official channels/i, '官方渠道发布反向叙事'],
  [/Polarized debate with mixed interpretations/i, '多方解读导致观点分化'],
  [/People repost first, verify later\./i, '先转发后核验的传播行为增加风险。'],
  [/Official clarification tempers the discussion\./i, '官方澄清可在一定程度上缓和争议。'],
  [/Different camps argue over incomplete evidence\./i, '不同阵营围绕不完整证据形成争论。'],
  [/Clip out of context on/i, '断章取义内容在以下平台传播：'],
  [/Rumor amplification in first/i, '谣言在前期传播窗口被放大，时间约：'],
  [/hours/i, '小时'],
  [/Publish evidence-backed clarification early and pin source links\./i, '建议尽早发布带证据引用的澄清，并置顶来源链接。'],
];

export function zhRiskLabel(value: string): string {
  return riskLabelMap[value] ?? value;
}

export function zhRiskLevel(value: string): string {
  return riskLevelMap[value] ?? value;
}

export function zhStance(value: string): string {
  return stanceMap[value] ?? value;
}

export function zhScenario(value: string): string {
  return scenarioMap[value] ?? value;
}

export function zhDomain(value: string): string {
  return domainMap[value] ?? value;
}

export function zhSourceType(value?: string | null): string {
  if (!value) return '未知';
  return sourceTypeMap[value] ?? value;
}

export function zhEmotion(value: string): string {
  return emotionMap[value.toLowerCase()] ?? value;
}

export function zhSimulationStance(value: string): string {
  const lower = value.toLowerCase();
  return (
    simulationStanceMap[lower] ??
    stanceMap[lower] ??
    emotionMap[lower] ??
    value
  );
}

export function zhText(value: string | undefined | null): string {
  if (!value) return '';
  let output = value;
  for (const [pattern, replacement] of englishReasonMap) {
    output = output.replace(pattern, replacement);
  }
  for (const [pattern, replacement] of englishSimulationMap) {
    output = output.replace(pattern, replacement);
  }
  for (const [en, zh] of Object.entries(stanceMap)) {
    const regex = new RegExp(`\\b${en}\\b`, 'gi');
    output = output.replace(regex, zh);
  }
  return output;
}

export function zhClaimId(claimId: string): string {
  const match = claimId.match(/^c(\d+)$/i);
  if (match) {
    return `主张${match[1]}`;
  }
  return claimId;
}
