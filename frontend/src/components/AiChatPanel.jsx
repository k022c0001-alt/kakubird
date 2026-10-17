import React, { useEffect, useRef, useState } from 'react';
import { useAiChat } from '../hooks/useAiChat';
import AiChatHeader from './AiChatHeader';
import AiChatMessageList from './AiChatMessageList';
import AiChatInput from './AiChatInput';
import MemoryDrawer from './MemoryDrawer';
import ZipUploadModal from './ZipUploadModal';
import ManualEditModal from './ManualEditModal';

// VS Code Webview 用の Window 拡張定義
declare global {
  interface Window {
    acquireVsCodeApi?: () => {
      postMessage: (message: any) => void;
      setState: (state: any) => void;
      getState: () => any;
    };
  }
}

// 型定義
export interface Screenshot {
  id: string;
  filename?: string;
  uri?: string | null;
  mime?: string;
  createdAt?: string;
  dataUrl?: string;
  pending?: boolean;
}

export type MemoryType = 'project' | 'rule' | 'knowledge' | 'experience' | 'template' | 'vector';

export interface MemoryItem {
  id?: string;
  payload?: any;
  pending?: boolean;
  createdAt?: string;
}

export type MemoriesState = Record<MemoryType, MemoryItem | null>;

export interface AiChatPanelProps {
  onImportDB?: (db: any) => void;
  onCreateDB?: () => void;
  onOpenManualEdit?: (block: any) => void;
}

export default function AiChatPanel({
  onImportDB,
  onCreateDB,
  onOpenManualEdit,
}: AiChatPanelProps) {
  // ---- UI states ----
  const [panelWidth, setPanelWidth] = useState<'normal' | 'wide'>('normal');
  const [isMemoryOpen, setIsMemoryOpen] = useState<boolean>(false);
  const [isPastingImage, setIsPastingImage] = useState<boolean>(false);
  const [zipModalState, setZipModalState] = useState<{ isOpen: boolean; file: File | null }>({
    isOpen: false,
    file: null,
  });

  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [memories, setMemories] = useState<MemoriesState>({
    project: null,
    rule: null,
    knowledge: null,
    experience: null,
    template: null,
    vector: null,
  });

  const savingIdsRef = useRef<Set<string>>(new Set());

  // VS Code API
  const vscode = typeof window !== 'undefined' && window.acquireVsCodeApi ? window.acquireVsCodeApi() : null;

  // Ai Chat hook
  const {
    messages,
    isLoading,
    sendMessage,
    sendImage,
    loadHistory,
    addSystemMessage,
    isRagMode,
    setIsRagMode,
    forceJsonMode,
    setForceJsonMode,
  } = useAiChat({ onImportDB });

  // Utility: write memory to fallback storage
  const fallbackSaveMemory = (type: MemoryType, payload: any) => {
    try {
      const key = `ai_mem_${type}`;
      localStorage.setItem(key, JSON.stringify({ payload, updatedAt: new Date().toISOString() }));
      return { id: `${type}-${Date.now()}`, savedAt: new Date().toISOString() };
    } catch (e) {
      console.error('fallbackSaveMemory failed', e);
      return null;
    }
  };

  // Unified memory save
  const saveMemory = async (type: MemoryType, payload: any) => {
    const tempId = `mem-temp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setMemories((prev) => ({
      ...prev,
      [type]: { id: tempId, payload, pending: true, createdAt: new Date().toISOString() },
    }));

    if (vscode) {
      vscode.postMessage({ command: 'saveMemory', type, payload, tempId });
      return;
    }

    const meta = fallbackSaveMemory(type, payload);
    if (meta) {
      setMemories((prev) => ({
        ...prev,
        [type]: { id: meta.id, payload, pending: false, createdAt: meta.savedAt },
      }));
      addSystemMessage(`ローカルに ${type} メモリを保存しました`);
    } else {
      addSystemMessage(`メモリ保存に失敗しました (${type})`);
    }
  };

  // Unified screenshot save
  const saveScreenshotToExtension = async (file: File) => {
    if (!file) return;
    const tempId = `shot-temp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const filename = file.name || `screenshot-${Date.now()}.png`;

    const dataUrl = await new Promise<string>((res, rej) => {
      const reader = new FileReader();
      reader.onload = () => res(reader.result as string);
      reader.onerror = rej;
      reader.readAsDataURL(file);
    });

    const optimistic: Screenshot = {
      id: tempId,
      filename,
      uri: null,
      mime: file.type || 'image/png',
      createdAt: new Date().toISOString(),
      dataUrl,
      pending: true,
    };
    setScreenshots((prev) => [optimistic, ...prev]);
    savingIdsRef.current.add(tempId);

    if (vscode) {
      const base64 = dataUrl.split(',')[1];
      vscode.postMessage({ command: 'saveScreenshot', filename, data: base64, mime: file.type || 'image/png', tempId });
      return;
    }

    try {
      const key = `ai_screenshot_${tempId}`;
      localStorage.setItem(key, dataUrl);
      const meta = { id: `local-${tempId}`, filename, uri: key, mime: file.type || 'image/png', createdAt: new Date().toISOString() };
      setScreenshots((prev) => prev.map((s) => (s.id === tempId ? { ...s, ...meta, dataUrl, pending: false } : s)));
      savingIdsRef.current.delete(tempId);
      addSystemMessage(`スクリーンショットをローカルに保存しました: ${filename}`);
    } catch (e) {
      console.error('fallback screenshot save failed', e);
      setScreenshots((prev) => prev.filter((s) => s.id !== tempId));
      savingIdsRef.current.delete(tempId);
      addSystemMessage('スクリーンショット保存に失敗しました（ローカル）');
    }
  };

  // Handle messages from extension
  useEffect(() => {
    const handleMessage = (ev: MessageEvent) => {
      const msg = ev.data;
      if (!msg || !msg.command) return;

      if (msg.command === 'screenshotSaved') {
        const metadata = msg.metadata || {};
        const { tempId } = msg;
        setScreenshots((prev) => {
          if (tempId) {
            return prev.map((s) => (s.id === tempId ? { ...s, ...metadata, pending: false } : s));
          }
          const exists = prev.find((s) => s.id === metadata.id || s.uri === metadata.uri);
          if (exists) return prev.map((s) => (s.id === exists.id ? { ...s, ...metadata, pending: false } : s));
          return [{ ...metadata, pending: false }, ...prev];
        });
        if (tempId) savingIdsRef.current.delete(tempId);
        addSystemMessage(`スクリーンショットを保存しました: ${metadata.filename || metadata.uri}`);
      } else if (msg.command === 'screenshotSaveFailed') {
        const { tempId, error } = msg;
        setScreenshots((prev) => prev.filter((s) => s.id !== tempId));
        if (tempId) savingIdsRef.current.delete(tempId);
        addSystemMessage(`スクリーンショット保存失敗: ${error}`);
      } else if (msg.command === 'memorySaved') {
        const { type, metadata } = msg as { type: MemoryType; metadata: any };
        setMemories((prev) => ({ ...prev, [type]: { ...(prev[type] || {}), ...metadata, pending: false } }));
        addSystemMessage(`${type} メモリを保存しました`);
      } else if (msg.command === 'memorySaveFailed') {
        const { type, error } = msg as { type: MemoryType; error: string };
        setMemories((prev) => ({ ...prev, [type]: { ...(prev[type] || {}), pending: false } }));
        addSystemMessage(`${type} メモリの保存に失敗しました: ${error}`);
      } else if (msg.command === 'screenshotIndex') {
        const list = Array.isArray(msg.list) ? msg.list : [];
        const normalized: Screenshot[] = list.map((it: any) => ({
          id: it.id || it.uri || `${it.filename}-${it.createdAt}`,
          filename: it.filename,
          uri: it.uri,
          mime: it.mime || 'image/png',
          createdAt: it.createdAt || new Date().toISOString(),
        }));
        setScreenshots((prev) => {
          const ids = new Set(prev.map((p) => p.id));
          const newItems = normalized.filter((n) => !ids.has(n.id));
          return [...newItems, ...prev];
        });
      } else if (msg.command === 'memoryIndex') {
        const map = msg.map || {};
        setMemories((prev) => ({ ...prev, ...map }));
      }
    };

    window.addEventListener('message', handleMessage);
    if (vscode) {
      try { vscode.postMessage({ command: 'requestIndex' }); } catch (e) {}
    } else {
      const loadFallback = () => {
        const keys: MemoryType[] = ['project', 'rule', 'knowledge', 'experience', 'template', 'vector'];
        const map: Partial<MemoriesState> = {};
        keys.forEach((k) => {
          const v = localStorage.getItem(`ai_mem_${k}`);
          if (v) {
            try { map[k] = JSON.parse(v).payload; } catch (e) { map[k] = null; }
          } else map[k] = null;
        });
        setMemories((prev) => ({ ...prev, ...map }));
      };
      loadFallback();
    }
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // Paste handling
  useEffect(() => {
    let timeoutId: NodeJS.Timeout;
    const handleGlobalPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageItem = Array.from(items).find((item) => item.type && item.type.startsWith('image/'));
      if (imageItem) {
        e.preventDefault();
        const file = imageItem.getAsFile();
        if (!file) return;

        setIsPastingImage(true);
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => setIsPastingImage(false), 2000);

        setIsMemoryOpen(true);
        saveScreenshotToExtension(file);
        if (sendImage) {
          sendImage(file).catch((err) => console.warn('sendImage error', err));
        }
      }
    };
    window.addEventListener('paste', handleGlobalPaste);
    return () => {
      window.removeEventListener('paste', handleGlobalPaste);
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [sendImage]);

  // Handler: delete screenshot
  const handleDeleteScreenshot = (shotId: string) => {
    if (!shotId) return;
    setScreenshots((prev) => prev.filter((s) => s.id !== shotId));
    if (vscode) {
      vscode.postMessage({ command: 'deleteScreenshot', id: shotId });
    } else {
      const key = shotId.startsWith('local-') ? shotId.replace('local-', '') : shotId;
      try { localStorage.removeItem(key); } catch (e) {}
    }
  };

  // Handler: use screenshot
  const handleUseScreenshot = (shot: Screenshot) => {
    if (!shot) return;
    if (shot.dataUrl) {
      const file = dataURLToFile(shot.dataUrl, shot.filename || 'screenshot.png');
      if (sendImage) sendImage(file).catch((e) => console.warn(e));
      addSystemMessage('スクリーンショットを解析に送信しました');
      return;
    }
    if (shot.uri) {
      navigator.clipboard.writeText(shot.uri);
      addSystemMessage('スクリーンショット URI をクリップボードにコピーしました');
    }
  };

  const dataURLToFile = (dataurl: string, filename: string): File => {
    const arr = dataurl.split(',');
    const mime = arr[0].match(/:(.*?);/)?.[1] || 'image/png';
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) u8arr[n] = bstr.charCodeAt(n);
    return new File([u8arr], filename, { type: mime });
  };

  const handleZipUpload = (file: File) => setZipModalState({ isOpen: true, file });
  const handleZipComplete = (completedFile?: File | null) => {
    const targetFile = completedFile || zipModalState.file;
    const fileName = targetFile ? targetFile.name : 'ソースコード';
    addSystemMessage(`📁 プロジェクト「${fileName}」のソースコードと構造を全て記憶しました。`);
    setIsRagMode(true);
  };

  const [editModalState, setEditModalState] = useState<{ isOpen: boolean; blockData: any }>({
    isOpen: false,
    blockData: null,
  });

  const openManualEdit = (block: any) => {
    if (onOpenManualEdit) return onOpenManualEdit(block);
    setEditModalState({ isOpen: true, blockData: block });
  };

  const handleInsertCode = (codeSnippet: string) => {
    if (vscode) {
      vscode.postMessage({ command: 'insertCode', code: codeSnippet });
    } else {
      navigator.clipboard.writeText(codeSnippet);
      addSystemMessage('コードをクリップボードにコピーしました');
    }
  };

  return (
    <div className={`relative flex flex-col h-full bg-white dark:bg-slate-900 border-l transition-all duration-300 ${panelWidth === 'wide' ? 'w-full' : 'w-full'} ${isPastingImage ? 'ring-4 ring-blue-500 shadow-[0_0_40px_rgba(59,130,246,0.3)]' : 'border-slate-200 dark:border-slate-800'}`}>
      {isPastingImage && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-blue-500/10 transition-all duration-300">
          <div className="bg-white dark:bg-slate-800 px-8 py-6 rounded-2xl shadow-2xl transform scale-105 flex flex-col items-center">
            <span className="text-5xl mb-3">📸</span>
            <p className="font-bold text-blue-600 dark:text-blue-400">スクリーンショットを読み込みました！</p>
            <p className="text-sm text-slate-500 mt-2">自動で保存・解析を行います</p>
          </div>
        </div>
      )}

      <AiChatHeader
        panelWidth={panelWidth}
        setPanelWidth={setPanelWidth}
        onCreateDB={onCreateDB}
        onLoadHistory={loadHistory}
        onOpenMemory={() => setIsMemoryOpen(true)}
        onDownloadZip={() => console.log('ZIPダウンロード')}
        onUploadImage={(file: File) => {
          saveScreenshotToExtension(file);
          if (sendImage) sendImage(file).catch((e) => console.warn(e));
        }}
        onUploadZip={handleZipUpload}
        onSaveProjectMemory={(meta: any) => saveMemory('project', meta)}
        onSaveRuleMemory={(rule: any) => saveMemory('rule', rule)}
      />

      <AiChatMessageList
        messages={messages}
        isLoading={isLoading}
        onOptionSelect={(selectedOptions: string[]) => {
          addSystemMessage(`選択結果: ${selectedOptions.join(', ')}`);
          if (selectedOptions.includes('自分で編集')) {
            const lastUiCodeMessage = [...messages].reverse().find((m) => m.type === 'ui_code');
            if (lastUiCodeMessage && lastUiCodeMessage.content?.blocks?.[0]) openManualEdit(lastUiCodeMessage.content.blocks[0]);
          }
        }}
        onOpenManualEdit={openManualEdit}
        onInsertCode={handleInsertCode}
      />

      <AiChatInput
        onSend={sendMessage}
        isLoading={isLoading}
        onSendImage={(file: File) => {
          saveScreenshotToExtension(file);
          if (sendImage) sendImage(file).catch((e) => console.warn(e));
        }}
        forceJsonMode={forceJsonMode}
        setForceJsonMode={setForceJsonMode}
      />

      <MemoryDrawer
        isOpen={isMemoryOpen}
        onClose={() => setIsMemoryOpen(false)}
        screenshots={screenshots}
        memories={memories}
        onUseScreenshot={handleUseScreenshot}
        onDeleteScreenshot={handleDeleteScreenshot}
        onSaveMemory={(type: MemoryType, payload: any) => saveMemory(type, payload)}
      />

      <ZipUploadModal
        isOpen={zipModalState.isOpen}
        file={zipModalState.file}
        onClose={() => setZipModalState({ isOpen: false, file: null })}
        onComplete={() => handleZipComplete(zipModalState.file)}
      />

      <ManualEditModal
        isOpen={editModalState.isOpen}
        blockData={editModalState.blockData}
        onClose={() => setEditModalState({ isOpen: false, blockData: null })}
        onSave={(updatedHtml: string, updatedCss: string) => {
          console.log('手動編集保存:', updatedHtml, updatedCss);
          setEditModalState({ isOpen: false, blockData: null });
          addSystemMessage('手動編集を保存しました');
        }}
      />
    </div>
  );
}
