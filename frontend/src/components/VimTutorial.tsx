import React, { useState } from 'react';
import { VimSandbox } from './VimSandbox';

interface VimTutorialProps {
  onClose: () => void;
}

export const VimTutorial: React.FC<VimTutorialProps> = ({ onClose }) => {
  // 現在表示している解説ページ（タブ）のステート
  const [currentPage, setCurrentPage] = useState<number>(1);

  // コマンドの定義（チートシート用）
  const commandList = [
    { cmd: "i", desc: "挿入モード (テキスト入力)" },
    { cmd: "Esc", desc: "ノーマルモード (コマンド入力)" },
    { cmd: ":w", desc: "保存" },
    { cmd: ":q", desc: "終了" },
    { cmd: ":wq", desc: "保存して終了" },
    { cmd: ":q!", desc: "保存せず終了" },
    { cmd: "dd", desc: "行削除 (カット)" },
    { cmd: "yy", desc: "行コピー" },
    { cmd: "p", desc: "貼り付け" },
    { cmd: "u", desc: "元に戻す (Undo)" },
    { cmd: "/検索語", desc: "検索" },
    { cmd: "n", desc: "次の検索結果へ" },
    { cmd: "gg", desc: "ファイルの先頭へ移動" },
    { cmd: "G", desc: "ファイルの末尾へ移動" },
  ];

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-6 md:p-10 backdrop-blur-sm">
      <div className="bg-slate-900 w-full max-w-6xl h-full max-h-[800px] rounded-2xl flex flex-col md:flex-row overflow-hidden border border-slate-700 shadow-2xl">
        
        {/* 左側：解説・コマンド表示エリア */}
        <div className="w-full md:w-[45%] flex flex-col bg-slate-800 text-slate-200 border-r border-slate-700">
          {/* ヘッダー部分 */}
          <div className="p-4 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
            <h2 className="text-lg font-bold text-green-400">Vim マスターへの道</h2>
            <button 
              onClick={onClose} 
              className="text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded transition"
            >
              閉じる ✕
            </button>
          </div>

          {/* コンテンツ部分 */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            
            {currentPage === 1 && (
              <div className="animate-fadeIn">
                <h3 className="text-2xl font-bold text-white mb-4">1. モードとファイル操作</h3>
                <p className="text-slate-300 mb-6 text-sm leading-relaxed">
                  Vim最大の罠であり、最大の特徴が「モード」です。文字を打つときは挿入モード、移動や保存をするときはノーマルモードを使います。
                </p>
                <div className="space-y-3">
                  <CommandCard cmd="i" desc="挿入モードへ (文字が打てるようになります)" />
                  <CommandCard cmd="Esc" desc="ノーマルモードへ (迷ったらとりあえずコレ)" />
                  <CommandCard cmd=":w" desc="上書き保存 (write)" />
                  <CommandCard cmd=":q" desc="終了 (quit)" />
                  <CommandCard cmd=":wq" desc="保存して終了" />
                  <CommandCard cmd=":q!" desc="強制終了 (保存せずに閉じる)" />
                </div>
              </div>
            )}

            {currentPage === 2 && (
              <div className="animate-fadeIn">
                <h3 className="text-2xl font-bold text-white mb-4">2. 爆速のテキスト編集</h3>
                <p className="text-slate-300 mb-6 text-sm leading-relaxed">
                  マウスで選択して右クリック...という手間は不要です。キーボードのキーを2回叩くだけで、行の削除やコピーが完了します。
                </p>
                <div className="space-y-3">
                  <CommandCard cmd="dd" desc="現在いる行を削除（切り取り）" />
                  <CommandCard cmd="yy" desc="現在いる行をコピー (yank)" />
                  <CommandCard cmd="p" desc="コピー/削除した内容を貼り付け (paste)" />
                  <CommandCard cmd="u" desc="ひとつ前の状態に戻す (undo)" />
                </div>
              </div>
            )}

            {currentPage === 3 && (
              <div className="animate-fadeIn">
                <h3 className="text-2xl font-bold text-white mb-4">3. 瞬間移動と検索</h3>
                <p className="text-slate-300 mb-6 text-sm leading-relaxed">
                  長いコードや文章の中で、スクロールバーを引っ張る必要はありません。狙った場所に一瞬で飛びましょう。
                </p>
                <div className="space-y-3">
                  <CommandCard cmd="gg" desc="ファイルの1番上へワープ" />
                  <CommandCard cmd="G" desc="ファイルの1番下へワープ" />
                  <CommandCard cmd="/検索語" desc="下方向へテキスト検索 (例: /react)" />
                  <CommandCard cmd="n" desc="次の検索ヒット箇所へ移動 (next)" />
                </div>
              </div>
            )}

            {currentPage === 4 && (
              <div className="animate-fadeIn">
                <h3 className="text-2xl font-bold text-white mb-4">📖 全コマンド一覧</h3>
                <div className="grid grid-cols-1 gap-2">
                  {commandList.map((item, idx) => (
                    <div key={idx} className="flex items-center bg-slate-900/50 p-2 rounded border border-slate-700/50">
                      <span className="text-green-400 font-mono font-bold w-16 shrink-0">{item.cmd}</span>
                      <span className="text-sm text-slate-300">{item.desc}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ナビゲーション（タブ） */}
          <div className="p-4 bg-slate-900/80 border-t border-slate-700 grid grid-cols-4 gap-2">
            <NavButton page={1} current={currentPage} setPage={setCurrentPage} label="1. 基本" />
            <NavButton page={2} current={currentPage} setPage={setCurrentPage} label="2. 編集" />
            <NavButton page={3} current={currentPage} setPage={setCurrentPage} label="3. 移動" />
            <NavButton page={4} current={currentPage} setPage={setCurrentPage} label="📋 辞書" />
          </div>
        </div>

        {/* 右側：実践エリア (VimSandbox) */}
        <div className="w-full md:w-[55%] p-6 bg-[#1e1e1e] flex flex-col">
          <div className="flex justify-between items-end mb-4">
            <div>
              <h3 className="text-white font-bold">サンドボックス</h3>
              <p className="text-xs text-slate-400 mt-1">左のコマンドを実際に叩いて試せます</p>
            </div>
            <div className="text-xs text-slate-500">※一部コマンドは開発中です</div>
          </div>
          
          <div className="flex-1 rounded-lg overflow-hidden shadow-inner flex">
            {/* 既存の VimSandbox コンポーネントを配置 */}
            <VimSandbox />
          </div>
        </div>

      </div>
    </div>
  );
};

// --- サブコンポーネント: コマンドのカード表示 ---
const CommandCard = ({ cmd, desc }: { cmd: string; desc: string }) => (
  <div className="bg-slate-700/30 border border-slate-600 rounded-lg p-3 flex items-center hover:bg-slate-700/50 transition">
    <div className="bg-slate-900 text-green-400 font-mono font-bold px-3 py-1.5 rounded-md min-w-[3.5rem] text-center shrink-0 shadow-sm border border-slate-800">
      {cmd}
    </div>
    <div className="ml-4 text-sm font-medium text-slate-200">
      {desc}
    </div>
  </div>
);

// --- サブコンポーネント: 下部のタブボタン ---
const NavButton = ({ 
  page, 
  current, 
  setPage, 
  label 
}: { 
  page: number; 
  current: number; 
  setPage: (p: number) => void; 
  label: string;
}) => {
  const isActive = page === current;
  return (
    <button
      onClick={() => setPage(page)}
      className={`py-2 px-1 text-xs font-bold rounded transition ${
        isActive 
          ? "bg-green-600 text-white shadow-md" 
          : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
      }`}
    >
      {label}
    </button>
  );
};
