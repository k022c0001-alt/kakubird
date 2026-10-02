import React from 'react';

function SourceLink({ href, children }) {
  if (!href || !/^https?:\/\//i.test(href)) return null;
  return (
    <a
      className="text-blue-600 dark:text-blue-400 underline break-all"
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      {children || href}
    </a>
  );
}

export default function StockResearchBlock({ data }) {
  if (!data || !Array.isArray(data.stocks)) {
    return <div className="text-sm">株式調査データを表示できません。</div>;
  }

  return (
    <section className="space-y-3" aria-label="株式調査結果">
      <div className="text-xs text-slate-500 dark:text-slate-400">
        対象: {data.universe?.symbols?.join(', ') || '未指定'} ・
        {data.universe?.coverage || '限定された銘柄のみ'}
      </div>
      {data.stocks.map((stock) => {
        const price = stock.price || {};
        const performance = stock.business_performance || {};
        const reports = stock.official_reports || {};
        return (
          <article
            key={stock.symbol}
            className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-2"
          >
            <h3 className="font-semibold">{stock.symbol}</h3>
            {price.status === 'available' ? (
              <div className="text-sm space-y-1">
                <div>
                  期間騰落率: {price.change_percent > 0 ? '+' : ''}
                  {price.change_percent}% ({price.period_start}〜{price.period_end})
                </div>
                <div>
                  上昇日 {price.up_moves} / 下落日 {price.down_moves} / 方向反転{' '}
                  {price.alternating_moves}回
                  {price.repeated_alternation ? '（反復あり）' : ''}
                </div>
                <div>
                  最新終値: {price.latest_close} {price.currency || ''} ・基準日:{' '}
                  {price.as_of || '不明'}
                </div>
                <div>
                  株価出典: <SourceLink href={price.source_url}>{price.source}</SourceLink>
                </div>
              </div>
            ) : (
              <p className="text-sm text-amber-700 dark:text-amber-300">
                株価データ取得不可: {price.reason || '利用できません'}
                {price.source_url && (
                  <>
                    {' '}<SourceLink href={price.source_url}>出典</SourceLink>
                  </>
                )}
              </p>
            )}
            <p className="text-sm text-amber-700 dark:text-amber-300">
              業績比較: 利用不可。{performance.reason || '財務数値を取得できません。'}{' '}
              {performance.cadence_note}
            </p>
            <div className="text-sm">
              <div className="font-medium">公式開示</div>
              {reports.status === 'available' && reports.reports?.length ? (
                <ul className="list-disc pl-5">
                  {reports.reports.map((report) => (
                    <li key={report.document_id || report.title}>
                      {report.title}（{report.submitted_at || '提出日不明'}）—
                      メタデータのみ。本文・財務内容は要確認。
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-amber-700 dark:text-amber-300">
                  {reports.reason || '公式開示を取得できません。'}
                </p>
              )}
              {reports.source_url && (
                <div>
                  開示出典: <SourceLink href={reports.source_url}>{reports.source || 'EDINET'}</SourceLink>
                  {reports.as_of && ` ・基準日: ${reports.as_of}`}
                </div>
              )}
            </div>
          </article>
        );
      })}
      <ul className="list-disc pl-5 text-xs text-slate-500 dark:text-slate-400">
        {(data.disclosures || []).map((disclosure) => (
          <li key={disclosure}>{disclosure}</li>
        ))}
      </ul>
    </section>
  );
}
