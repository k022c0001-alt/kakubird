import React, { useState, useEffect, useCallback } from "react";

type Mode = "NORMAL" | "INSERT" | "COMMAND";

const INITIAL_TEXT = [
  "Welcome to Vim Simulator!",
  "Here is a safe place to practice.",
  "Try clicking the buttons above, or use your keyboard.",
  "1. Press 'dd' to delete this line.",
  "2. Press 'yy' to copy, and 'p' to paste.",
  "3. Press 'u' to undo any mistakes.",
  "Let's master Vim together!"
];

export const VimSandbox: React.FC = () => {
  // --- エディタの状態 ---
  const [lines, setLines] = useState<string[]>(INITIAL_TEXT);
  const [cursor, setCursor] = useState<{ row: number; col: number }>({ row: 0, col: 0 });
  const [mode, setMode] = useState<Mode>("NORMAL");
  
  // --- Vim特有の状態 ---
  const [keyBuffer, setKeyBuffer] = useState<string>(""); // 連続キー(dd, yyなど)の記憶用
  const [clipboard, setClipboard] = useState<string | null>(null); // yy, ddで保持するデータ
  const [history, setHistory] = useState<string[][]>([]); // u (元に戻す) 用の履歴
  const [commandText, setCommandText] = useState<string>(""); // :w などのコマンド入力用
  const [message, setMessage] = useState<string>(""); // ステータスバーへの通知

  // --- 履歴を保存する関数（変更を加える前に呼ぶ） ---
  const saveHistory = useCallback((currentLines: string[]) => {
    setHistory(prev => [...prev, currentLines]);
  }, []);

  // --- メッセージを表示して数秒後に消す ---
  const showMessage = useCallback((msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  }, []);

  // --- カーソル位置の補正 ---
  const clampCursor = (r: number, c: number, currentLines: string[]) => {
    const row = Math.max(0, Math.min(currentLines.length - 1, r));
    const maxCol = Math.max(0, currentLines[row].length - (mode === "NORMAL" ? 1 : 0));
    const col = Math.max(0, Math.min(maxCol, c));
    return { row, col };
  };

  // --- コマンド実行エンジン（ボタン・キー共通） ---
  const executeCommand = useCallback((cmd: string) => {
    if (mode !== "NORMAL") return;

    setLines(prevLines => {
      let newLines = [...prevLines];
      let newCursor = { ...cursor };
      let handled = true;

      switch (cmd) {
        // --- モード切替 ---
        case "i":
          setMode("INSERT");
          handled = false; // 状態だけ変えて終了
          break;
        case "Esc":
          setKeyBuffer("");
          break;

        // --- 移動系 ---
        case "h":
          newCursor.col -= 1;
          break;
        case "l":
          newCursor.col += 1;
          break;
        case "j":
          newCursor.row += 1;
          break;
        case "k":
          newCursor.row -= 1;
          break;
        case "gg":
          newCursor = { row: 0, col: 0 };
          showMessage("先頭へ移動しました");
          break;
        case "G":
          newCursor = { row: newLines.length - 1, col: 0 };
          showMessage("末尾へ移動しました");
          break;

        // --- 編集系 ---
        case "x":
          saveHistory(prevLines);
          if (newLines[cursor.row].length > 0) {
            const line = newLines[cursor.row];
            newLines[cursor.row] = line.slice(0, cursor.col) + line.slice(cursor.col + 1);
          }
          break;
        case "dd":
          saveHistory(prevLines);
          setClipboard(newLines[cursor.row]);
          newLines.splice(cursor.row, 1);
          if (newLines.length === 0) newLines = [""]; // 空ファイル防止
          showMessage("1行削除 (カット) しました");
          break;
        case "yy":
          setClipboard(newLines[cursor.row]);
          showMessage("1行コピーしました");
          handled = false; // 画面の変更はなし
          break;
        case "p":
          if (clipboard !== null) {
            saveHistory(prevLines);
            // 現在の行の下に挿入
            newLines.splice(cursor.row + 1, 0, clipboard);
            newCursor.row += 1;
            showMessage("貼り付けました");
          } else {
            showMessage("クリップボードは空です");
            handled = false;
          }
          break;
        case "u":
          if (history.length > 0) {
            const previousState = history[history.length - 1];
            setHistory(prev => prev.slice(0, -1));
            newLines = [...previousState];
            showMessage("元に戻しました (Undo)");
          } else {
            showMessage("これ以上戻せません");
            handled = false;
          }
          break;

        // --- コマンド系 ---
        case ":w":
          showMessage(`"${INITIAL_TEXT[0].split(' ')[0]}.txt" を保存しました`);
          handled = false;
          break;
        case ":q":
          showMessage("終了コマンドが呼ばれました");
          handled = false;
          break;
        case ":wq":
          showMessage("保存して終了します");
          handled = false;
          break;
        case ":q!":
          showMessage("変更を破棄して終了します");
          handled = false;
          break;

        default:
          handled = false;
          break;
      }

      if (handled) {
        setCursor(clampCursor(newCursor.row, newCursor.col, newLines));
        return newLines;
      }
      return prevLines;
    });
  }, [mode, cursor, clipboard, history, saveHistory, showMessage]);

  // --- キーボード入力監視 ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 矢印キーなどのデフォルトスクロールを防ぐ
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
      }

      if (mode === "NORMAL") {
        if (e.key === "Escape") {
          setKeyBuffer("");
          return;
        }

        if (e.key === ":") {
          e.preventDefault();
          setMode("COMMAND");
          setCommandText(":");
          return;
        }

        // 単一キーコマンド
        if (["h", "j", "k", "l", "i", "x", "p", "u", "G"].includes(e.key)) {
          executeCommand(e.key);
          setKeyBuffer("");
        } 
        // 連続キーコマンド (dd, yy, gg) の処理
        else if (["d", "y", "g"].includes(e.key)) {
          const newBuffer = keyBuffer + e.key;
          if (newBuffer === "dd" || newBuffer === "yy" || newBuffer === "gg") {
            executeCommand(newBuffer);
            setKeyBuffer(""); // リセット
          } else {
            setKeyBuffer(newBuffer);
            // 1秒待って完成しなかったらリセット
            setTimeout(() => setKeyBuffer(""), 1000);
          }
        }
      } 
      
      else if (mode === "INSERT") {
        if (e.key === "Escape") {
          setMode("NORMAL");
          // ノーマルに戻るときはカーソルを1つ左へ
          setCursor(prev => clampCursor(prev.row, prev.col - 1, lines));
        } else if (e.key === "Enter") {
          e.preventDefault();
          saveHistory(lines);
          setLines(prev => {
            const newLines = [...prev];
            const line = newLines[cursor.row];
            const before = line.slice(0, cursor.col);
            const after = line.slice(cursor.col);
            newLines[cursor.row] = before;
            newLines.splice(cursor.row + 1, 0, after);
            return newLines;
          });
          setCursor(prev => ({ row: prev.row + 1, col: 0 }));
        } else if (e.key === "Backspace") {
          saveHistory(lines);
          if (cursor.col > 0) {
            setLines(prev => {
              const newLines = [...prev];
              const line = newLines[cursor.row];
              newLines[cursor.row] = line.slice(0, cursor.col - 1) + line.slice(cursor.col);
              return newLines;
            });
            setCursor(prev => ({ ...prev, col: prev.col - 1 }));
          } else if (cursor.row > 0) {
            // 前の行と結合
            setLines(prev => {
              const newLines = [...prev];
              const prevLineLength = newLines[cursor.row - 1].length;
              newLines[cursor.row - 1] += newLines[cursor.row];
              newLines.splice(cursor.row, 1);
              setCursor({ row: cursor.row - 1, col: prevLineLength });
              return newLines;
            });
          }
        } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
          saveHistory(lines);
          setLines(prev => {
            const newLines = [...prev];
            const line = newLines[cursor.row];
            newLines[cursor.row] = line.slice(0, cursor.col) + e.key + line.slice(cursor.col);
            return newLines;
          });
          setCursor(prev => ({ ...prev, col: prev.col + 1 }));
        }
      } 
      
      else if (mode === "COMMAND") {
        if (e.key === "Escape") {
          setMode("NORMAL");
          setCommandText("");
        } else if (e.key === "Enter") {
          executeCommand(commandText);
          setMode("NORMAL");
          setCommandText("");
        } else if (e.key === "Backspace") {
          setCommandText(prev => prev.length > 1 ? prev.slice(0, -1) : ":");
        } else if (e.key.length === 1) {
          setCommandText(prev => prev + e.key);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mode, cursor, lines, keyBuffer, commandText, executeCommand, saveHistory]);

  // --- お助けボタンコンポーネント ---
  const HelperButton = ({ label, cmd, highlight = false }: { label: string; cmd: string; highlight?: boolean }) => (
    <button
      onClick={() => {
        if (cmd === "Esc") setMode("NORMAL");
        else executeCommand(cmd);
      }}
      className={`text-xs px-2 py-1 rounded transition border ${
        highlight 
          ? "bg-blue-600 border-blue-500 text-white hover:bg-blue-500" 
          : "bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col w-full h-full bg-[#1e1e1e] rounded-lg overflow-hidden">
      
      {/* お助けツールバー（クリックでコマンド実行） */}
      <div className="bg-slate-900 border-b border-slate-700 p-2 flex flex-wrap gap-2 items-center">
        <span className="text-xs text-slate-500 mr-2">ワンクリック操作:</span>
        <HelperButton label="Esc (ノーマル)" cmd="Esc" highlight={mode !== "NORMAL"} />
        <HelperButton label="i (挿入)" cmd="i" highlight={mode === "NORMAL"} />
        <div className="w-px h-4 bg-slate-700 mx-1"></div>
        <HelperButton label="dd (行削除)" cmd="dd" />
        <HelperButton label="yy (行コピー)" cmd="yy" />
        <HelperButton label="p (貼付)" cmd="p" />
        <HelperButton label="u (戻す)" cmd="u" />
        <div className="w-px h-4 bg-slate-700 mx-1"></div>
        <HelperButton label="gg (先頭)" cmd="gg" />
        <HelperButton label="G (末尾)" cmd="G" />
        <div className="w-px h-4 bg-slate-700 mx-1"></div>
        <HelperButton label=":w (保存)" cmd=":w" />
      </div>

      {/* エディタ描画エリア */}
      <div 
        className="flex-1 p-4 font-mono text-[14px] leading-relaxed overflow-y-auto cursor-text"
        onClick={() => mode !== "NORMAL" && setMode("NORMAL")} // 背景クリックでノーマルに戻る補助
      >
        {lines.map((line, rIndex) => (
          <div key={rIndex} className="flex">
            {/* 行番号 */}
            <span className="w-8 text-right pr-4 text-slate-600 select-none">
              {rIndex + 1}
            </span>
            
            {/* 行のテキスト */}
            <span className="relative whitespace-pre text-slate-300">
              {line.length === 0 && rIndex === cursor.row && (
                <span className={`inline-block w-2 ${mode === "NORMAL" ? "bg-slate-400 opacity-50" : "bg-white"} h-[1em]`}></span>
              )}
              {line.split("").map((char, cIndex) => {
                const isCursor = rIndex === cursor.row && cIndex === cursor.col;
                return (
                  <span
                    key={cIndex}
                    className={`${
                      isCursor
                        ? mode === "NORMAL"
                          ? "bg-slate-400 text-black" // ノーマルモード：ブロックカーソル
                          : "border-l-2 border-white -ml-[2px]" // インサートモード：縦線カーソル
                        : ""
                    }`}
                  >
                    {char}
                  </span>
                );
              })}
              {/* 行末のカーソル対応 */}
              {rIndex === cursor.row && cursor.col >= line.length && line.length > 0 && (
                <span className={`inline-block ${mode === "NORMAL" ? "bg-slate-400 text-black w-2" : "border-l-2 border-white -ml-[2px] w-[1px]"} h-[1em]`}></span>
              )}
            </span>
          </div>
        ))}
      </div>

      {/* ステータスバー */}
      <div className="bg-blue-600 text-white text-xs px-4 py-1.5 flex justify-between font-bold">
        <div className="flex gap-4">
          <span>{mode === "NORMAL" ? "NORMAL" : mode === "INSERT" ? "-- INSERT --" : "COMMAND"}</span>
          <span className="text-blue-200 font-normal">{message || (mode === "COMMAND" ? commandText : "")}</span>
        </div>
        <div>
          {cursor.row + 1}:{cursor.col + 1}
        </div>
      </div>
    </div>
  );
};
