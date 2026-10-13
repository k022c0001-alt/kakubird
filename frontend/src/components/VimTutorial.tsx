import React, { useState } from 'react';
import { VimSandbox } from './VimSandbox';

interface VimTutorialProps {
  onClose: () => void;
}

export const VimTutorial: React.FC<VimTutorialProps> = ({ onClose }) => {
  const [currentPage, setCurrentPage] = useState(1);
  const totalPages = 3;

  // 便利な時短コマンドのデータリスト
  const advancedCommands = [
    { key: 'w', desc: '次の単語の先頭にジャンプ' },
    { key: 'b', desc: '前の単語の先頭にジャンプ' },
    { key: 'dd', desc: 'カーソル行を1行カット（削除）' },
    { key: 'yy', desc: 'カーソル行を1行コピー' },
    { key: 'p', desc: 'カット・コピーしたものをペースト' },
    { key: 'u', desc: '操作をひとつ取り消す（Undo）' },
    { key: '0', desc: '行の先頭へジャンプ' },
    { key: '$', desc: '行の末尾へジャンプ' },
  ];

  const renderContent = () => {
    switch (currentPage) {
      case 1:
        return (
          <div className="space-y-4 animate-fade-in">
            <h2 className="text-2xl font-bold text-white mb-2">1. Vimの役割と基本思想</h2>
            <p className="text-slate-300 leading-relaxed">
              Vimは単なるテキストエディタではなく、<strong className="text-blue-400">「マウスに手を伸ばす時間を削り、思考のスピードでテキストを編集する」</strong>ための思想です。
            </p>
            <div className="bg-slate-800 p-4 rounded-lg border border-slate-700 mt-4">
              <h3 className="text-lg font-semibold text-blue-300 mb-2">💡 2つのモード</h3>
              <ul className="list-disc list-inside space-y-2 text-slate-300">
                <li><strong>ノーマルモード:</strong> 文字を入力せず、移動や削除、コピーなどの「操作」を行う基本状態。</li>
                <li><strong>インサートモード:</strong> 普通のエディタのように文字を「入力」する状態。</li>
              </ul>
            </div>
            <p className="text-slate-400 text-sm mt-4">
              ※常に<kbd className="bg-slate-700 px-1.5 py-0.5 rounded mx-1">Esc</kbd>を押して「ノーマルモード」に戻るのがVimの基本動作です。
            </p>
          </div>
        );
      case 2:
        return (
          <div className="space-y-4 animate-fade-in">
            <h2 className="text-2xl font-bold text-white mb-2">2. ホームポジションでの移動</h2>
            <p className="text-slate-300 leading-relaxed">
              右のサンドボックスをクリックし、矢印キーを使わずに以下のキーを押してみてください。
            </p>
            <div className="grid grid-cols-2 gap-3 mt-4">
              <div className="bg-slate-800 p-3 rounded border border-slate-700 text-center">
                <kbd className="text-xl font-mono text-green-400">h</kbd>
                <p className="text-slate-400 text-sm mt-1">左へ移動</p>
              </div>
              <div className="bg-slate-800 p-3 rounded border border-slate-700 text-center">
                <kbd className="text-xl font-mono text-green-400">l</kbd>
                <p className="text-slate-400 text-sm mt-1">右へ移動</p>
              </div>
              <div className="bg-slate-800 p-3 rounded border border-slate-700 text-center">
                <kbd className="text-xl font-mono text-green-400">k</kbd>
                <p className="text-slate-400 text-sm mt-1">上へ移動</p>
              </div>
              <div className="bg-slate-800 p-3 rounded border border-slate-700 text-center">
                <kbd className="text-xl font-mono text-green-400">j</kbd>
                <p className="text-slate-400 text-sm mt-1">下へ移動</p>
              </div>
            </div>
            <p className="text-slate-300 mt-4">
              <kbd className="bg-slate-700 px-1.5 py-0.5 rounded mx-1 text-green-400">i</kbd>を押すと文字入力ができ、
              <kbd className="bg-slate-700 px-1.5 py-0.5 rounded mx-1 text-green-400">x</kbd>を押すとカーソル上の文字を1文字消せます。
            </p>
          </div>
        );
      case 3:
        return (
          <div className="space-y-4 animate-fade-in">
            <h2 className="text-2xl font-bold text-white mb-2">3. 便利な時短コマンド集</h2>
            <p className="text-slate-300 text-sm mb-4">
              これらを覚えると、一文字ずつ消したり移動したりする手間が一気に省けます。
              （※サンドボックスへの実装は順次拡張可能です）
            </p>
            <div className="space-y-2 max-h-[280px] overflow-y-auto pr-2 custom-scrollbar">
              {advancedCommands.map((cmd, idx) => (
                <div key={idx} className="flex items-center bg-slate-800 p-3 rounded border border-slate-700">
                  <div className="w-16 flex-shrink-0">
                    <kbd className="bg-black border border-slate-600 text-blue-400 font-mono px-2 py-1 rounded">
                      {cmd.key}
                    </kbd>
                  </div>
                  <div className="text-slate-300 text-sm">
                    {cmd.desc}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 md:p-10">
      {/* モーダルコンテナ */}
      <div className="bg-slate-900 w-full max-w-6xl h-full max-h-[700px] rounded-2xl flex flex-col md:flex-row overflow-hidden border border-slate-700 shadow-2xl">
        
        {/* 左側：解説エリア */}
        <div className="w-full md:w-5/12 bg-slate-900/50 p-6 md:p-8 flex flex-col border-b md:border-b-0 md:border-r border-slate-700 relative">
          <button 
            onClick={onClose}
            className="absolute top-4 left-4 text-slate-400 hover:text-white flex items-center text-sm transition"
          >
            ← 閉じる
          </button>
          
          <div className="mt-8 flex-1 overflow-y-auto">
            {renderContent()}
          </div>

          {/* ページネーション・ナビゲーション */}
          <div className="mt-6 flex items-center justify-between border-t border-slate-800 pt-4">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className={`px-4 py-2 rounded text-sm font-medium transition ${
                currentPage === 1 
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed' 
                  : 'bg-slate-700 text-white hover:bg-slate-600'
              }`}
            >
              前へ
            </button>
            <span className="text-slate-400 text-sm">
              {currentPage} / {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className={`px-4 py-2 rounded text-sm font-medium transition ${
                currentPage === totalPages 
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed' 
                  : 'bg-blue-600 text-white hover:bg-blue-500'
              }`}
            >
              次へ
            </button>
          </div>
        </div>

        {/* 右側：実践エリア (VimSandbox) */}
        <div className="w-full md:w-7/12 bg-black flex flex-col p-6 md:p-8 relative">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-slate-400 text-sm font-medium flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
              実践サンドボックス
            </h3>
            <span className="text-xs text-slate-500">
              ※ここをクリックしてキーボード操作
            </span>
          </div>
          
          <div className="flex-1 bg-slate-900 rounded-xl overflow-hidden border border-slate-800 flex items-center justify-center">
            {/* 以前作成したVimSandboxコンポーネントを配置 */}
            <VimSandbox />
          </div>
        </div>

      </div>
    </div>
  );
};
