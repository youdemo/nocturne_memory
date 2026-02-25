import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { 
  ChevronRight, 
  Folder, 
  FileText, 
  Edit3, 
  Save, 
  X, 
  Home, 
  Search, 
  Database, 
  Cpu, 
  Hash, 
  Layers, 
  ArrowLeft,
  AlertTriangle,
  Link2,
  Star
} from 'lucide-react';
import axios from 'axios';
import clsx from 'clsx';

// API Instance
const api = axios.create({ baseURL: '/api' });

// --- Helper ---
const PriorityBadge = ({ priority, size = 'sm' }) => {
  if (priority === null || priority === undefined) return null;
  
  const colors = priority === 0
    ? 'bg-rose-950/40 text-rose-400 border-rose-800/40'
    : priority <= 2
    ? 'bg-amber-950/30 text-amber-400 border-amber-800/30'
    : priority <= 5
    ? 'bg-sky-950/30 text-sky-400 border-sky-800/30'
    : 'bg-slate-800/30 text-slate-500 border-slate-700/30';
  
  const sizeClass = size === 'lg' 
    ? 'px-2.5 py-1 text-xs gap-1.5' 
    : 'px-1.5 py-0.5 text-[10px] gap-1';
  
  return (
    <span className={clsx("inline-flex items-center rounded border font-mono font-semibold", colors, sizeClass)}>
      <Star size={size === 'lg' ? 12 : 9} />
      {priority}
    </span>
  );
};

// --- Components ---

// 1. Sidebar Item
const SidebarItem = ({ icon: Icon, label, active, onClick, count }) => (
  <button 
    onClick={onClick}
    className={clsx(
      "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200 group",
      active 
        ? "bg-indigo-500/10 text-indigo-300 shadow-[0_0_10px_rgba(99,102,241,0.1)]" 
        : "text-slate-500 hover:bg-white/[0.03] hover:text-slate-300"
    )}
  >
    <Icon size={16} className={clsx("transition-colors", active ? "text-indigo-400" : "text-slate-600 group-hover:text-slate-400")} />
    <span className="flex-1 text-left truncate font-medium">{label}</span>
    {count !== undefined && (
      <span className="text-xs bg-slate-800/50 px-1.5 py-0.5 rounded text-slate-600 group-hover:text-slate-500">{count}</span>
    )}
  </button>
);

// 2. Breadcrumb
const Breadcrumb = ({ items, onNavigate }) => (
  <div className="flex items-center gap-2 overflow-x-auto no-scrollbar mask-linear-fade">
    <button 
      onClick={() => onNavigate('')}
      className="p-1.5 rounded-md hover:bg-slate-800/50 text-slate-500 hover:text-indigo-400 transition-colors"
    >
      <Home size={14} />
    </button>
    
    {items.map((crumb, i) => (
      <React.Fragment key={crumb.path}>
        <ChevronRight size={12} className="text-slate-700 flex-shrink-0" />
        <button
          onClick={() => onNavigate(crumb.path)}
          className={clsx(
            "px-2 py-1 rounded-md text-xs font-medium transition-all whitespace-nowrap",
            i === items.length - 1
              ? "bg-indigo-500/10 text-indigo-300 border border-indigo-500/20"
              : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
          )}
        >
          {crumb.label}
        </button>
      </React.Fragment>
    ))}
  </div>
);

// 3. Node Card (Grid View) - Redesigned
const NodeGridCard = ({ node, currentDomain, onClick }) => {
  const isCrossDomain = node.domain && node.domain !== currentDomain;
  return (
  <button 
    onClick={onClick}
    className={clsx(
      "group relative flex flex-col items-start p-5 bg-[#0A0A12] border rounded-xl transition-all duration-300 hover:shadow-[0_0_20px_rgba(99,102,241,0.1)] hover:-translate-y-1 text-left w-full h-full overflow-hidden",
      isCrossDomain
        ? "border-violet-800/40 hover:border-violet-500/40"
        : "border-slate-800/50 hover:border-indigo-500/30"
    )}
  >
    {/* Hover Gradient */}
    <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
    
    {/* Header: Icon + Name + Importance */}
    <div className="flex items-center gap-3 mb-3 w-full">
      <div className="p-2 rounded-lg bg-slate-900 group-hover:bg-indigo-900/20 text-slate-500 group-hover:text-indigo-400 transition-colors flex-shrink-0">
         {node.children_count > 0 ? <Folder size={18} /> : <FileText size={18} />}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-slate-300 group-hover:text-indigo-200 transition-colors break-words line-clamp-2">
          {node.name || node.path.split('/').pop()}
        </h3>
        {isCrossDomain && (
          <span className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 text-[10px] font-mono text-violet-400/80 bg-violet-950/40 border border-violet-800/30 rounded">
            <Link2 size={9} />
            {node.domain}://
          </span>
        )}
      </div>
      <PriorityBadge priority={node.priority} />
    </div>
    
    {/* Disclosure (if present) */}
    {node.disclosure && (
      <div className="w-full mb-2">
        <p className="text-[11px] text-amber-500/70 leading-snug line-clamp-2 flex items-start gap-1">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          <span className="italic">{node.disclosure}</span>
        </p>
      </div>
    )}
    
    {/* Content snippet */}
    <div className="w-full flex-1">
        {node.content_snippet ? (
            <p className="text-xs text-slate-500 leading-relaxed line-clamp-3">
                {node.content_snippet}
            </p>
        ) : (
            <p className="text-xs text-slate-700 italic">No preview available</p>
        )}
    </div>

    {/* Hover arrow - absolute positioned, no layout cost */}
    <ChevronRight size={14} className="absolute bottom-4 right-4 text-indigo-500/50 opacity-0 group-hover:opacity-100 transition-opacity" />
  </button>
  );
};


// --- Main Page ---

export default function MemoryBrowser() {
  const [searchParams, setSearchParams] = useSearchParams();
  const domain = searchParams.get('domain') || 'core';
  const path = searchParams.get('path') || '';
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState({ node: null, children: [], breadcrumbs: [] });
  const [domains, setDomains] = useState([]);
  
  // Edit State
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editDisclosure, setEditDisclosure] = useState('');
  const [editPriority, setEditPriority] = useState(0);
  const [saving, setSaving] = useState(false);

  // Fetch domain list
  useEffect(() => {
    api.get('/browse/domains').then(res => setDomains(res.data)).catch(() => {});
  }, []);

  // Fetch Data
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setEditing(false);
      try {
        const res = await api.get('/browse/node', { params: { domain, path } });
        setData(res.data);
        setEditContent(res.data.node?.content || '');
        setEditDisclosure(res.data.node?.disclosure || '');
        setEditPriority(res.data.node?.priority ?? 0);
      } catch (err) {
        setError(err.response?.data?.detail || err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [domain, path]);

  const navigateTo = (newPath, newDomain) => {
    const params = new URLSearchParams();
    params.set('domain', newDomain || domain);
    if (newPath) params.set('path', newPath);
    setSearchParams(params);
  };

  const startEditing = () => {
    setEditContent(data.node?.content || '');
    setEditDisclosure(data.node?.disclosure || '');
    setEditPriority(data.node?.priority ?? 0);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditContent(data.node?.content || '');
    setEditDisclosure(data.node?.disclosure || '');
    setEditPriority(data.node?.priority ?? 0);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {};
      // Only send changed fields
      if (editContent !== (data.node?.content || '')) {
        payload.content = editContent;
      }
      if (editPriority !== (data.node?.priority ?? 0)) {
        payload.priority = editPriority;
      }
      if (editDisclosure !== (data.node?.disclosure || '')) {
        payload.disclosure = editDisclosure;
      }
      
      if (Object.keys(payload).length === 0) {
        // Nothing changed
        setEditing(false);
        return;
      }
      
      await api.put('/browse/node', payload, { params: { domain, path } });
      const res = await api.get('/browse/node', { params: { domain, path } });
      setData(res.data);
      setEditing(false);
    } catch (err) {
      alert('Save failed: ' + err.message);
    } finally {
      setSaving(false);
    }
  };

  const isRoot = !path;
  const node = data.node;

  return (
    <div className="flex h-full bg-[#05050A] text-slate-300 font-sans selection:bg-indigo-500/30 selection:text-indigo-200 overflow-hidden">
      
      {/* 1. Sidebar Navigation */}
      <div className="w-64 flex-shrink-0 bg-[#08080E] border-r border-slate-800/30 flex flex-col">
        <div className="p-5 border-b border-slate-800/30">
          <div className="flex items-center gap-2 text-indigo-400 mb-1">
            <Cpu size={18} />
            <h1 className="font-bold tracking-tight text-sm text-slate-100">Memory Core</h1>
          </div>
          <p className="text-[10px] text-slate-600 pl-6 uppercase tracking-wider">Neural Explorer v2.0</p>
        </div>
        
        <div className="p-3 flex-1 overflow-y-auto">
             <div className="mb-4">
                 <h3 className="px-3 text-[10px] font-bold text-slate-600 uppercase tracking-widest mb-2">Domains</h3>
                 {domains.map(d => (
                   <SidebarItem
                     key={d.domain}
                     icon={Database}
                     label={d.domain.charAt(0).toUpperCase() + d.domain.slice(1) + ' Memory'}
                     active={domain === d.domain}
                     count={d.root_count}
                     onClick={() => navigateTo('', d.domain)}
                   />
                 ))}
                 {domains.length === 0 && (
                   <SidebarItem icon={Database} label="Core Memory" active={true} onClick={() => navigateTo('', 'core')} />
                 )}
             </div>
        </div>

        <div className="mt-auto p-4 border-t border-slate-800/30">
             <div className="bg-slate-900/50 rounded p-3 border border-slate-800/50">
                 <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
                    <Hash size={12} />
                    <span>Current Path</span>
                 </div>
                 <code className="block text-[10px] font-mono text-indigo-300/80 break-all leading-tight">
                    {domain}://{path || 'root'}
                 </code>
             </div>
        </div>
      </div>

      {/* 2. Main Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#05050A] relative">
         {/* Top Bar */}
         <div className="h-14 flex-shrink-0 border-b border-slate-800/30 flex items-center justify-between px-6 bg-[#05050A]/80 backdrop-blur-md sticky top-0 z-20">
             <Breadcrumb items={data.breadcrumbs} onNavigate={navigateTo} />
             
             <div className="flex items-center gap-2">
                 <div className="relative group">
                     <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-600 group-hover:text-slate-400 transition-colors" />
                     <input 
                        type="text" 
                        placeholder="Search nodes..." 
                        disabled
                        className="bg-slate-900/50 border border-slate-800 rounded-full py-1.5 pl-9 pr-4 text-xs text-slate-300 focus:outline-none focus:border-indigo-500/50 focus:bg-slate-900 transition-all w-48 cursor-not-allowed opacity-50"
                     />
                 </div>
             </div>
         </div>

         {/* Content Scroll Area */}
         <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
            {loading ? (
                <div className="h-full flex flex-col items-center justify-center gap-4 text-slate-600">
                    <div className="w-8 h-8 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                    <span className="text-xs tracking-widest uppercase">Retrieving Neural Data...</span>
                </div>
            ) : error ? (
                <div className="h-full flex flex-col items-center justify-center text-rose-500 gap-4">
                    <p className="text-lg">Access Denied / Error</p>
                    <p className="text-sm opacity-60">{error}</p>
                    <button onClick={() => navigateTo('')} className="text-xs bg-slate-800 px-4 py-2 rounded hover:text-white transition-colors">Return to Root</button>
                </div>
            ) : (
                <div className="max-w-7xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                    
                    {/* Node Header & Content (If not root) */}
                    {!isRoot && node && (
                        <div className="space-y-4">
                             {/* Header */}
                            <div className="flex items-start justify-between gap-4">
                                <div className="space-y-3 min-w-0 flex-1">
                                    {/* Title + Importance */}
                                    <div className="flex items-center gap-3 flex-wrap">
                                        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">
                                            {node.name || path.split('/').pop()}
                                        </h1>
                                        <PriorityBadge priority={node.priority} size="lg" />
                                    </div>
                                    
                                    {/* Disclosure */}
                                    {node.disclosure && !editing && (
                                        <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-amber-950/20 border border-amber-900/30 rounded-lg text-amber-500/80 text-xs max-w-full">
                                            <AlertTriangle size={14} className="flex-shrink-0" />
                                            <span className="font-medium mr-1">Disclosure:</span>
                                            <span className="italic truncate">{node.disclosure}</span>
                                        </div>
                                    )}
                                    
                                    {/* Aliases */}
                                    {node.aliases && node.aliases.length > 0 && !editing && (
                                        <div className="flex items-start gap-2 text-xs text-slate-500">
                                            <Link2 size={13} className="flex-shrink-0 mt-0.5 text-slate-600" />
                                            <div className="flex flex-wrap gap-1.5">
                                                <span className="text-slate-600 font-medium">Also reachable via:</span>
                                                {node.aliases.map(alias => (
                                                    <code key={alias} className="px-1.5 py-0.5 bg-slate-800/60 rounded text-indigo-400/70 font-mono text-[11px]">
                                                        {alias}
                                                    </code>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                
                                {/* Edit / Save buttons */}
                                <div className="flex gap-2 flex-shrink-0">
                                    {editing ? (
                                        <>
                                            <button onClick={cancelEditing} className="p-2 hover:bg-slate-800 rounded text-slate-400 transition-colors"><X size={18} /></button>
                                            <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-sm font-medium transition-colors shadow-lg shadow-indigo-900/20">
                                                <Save size={16} /> {saving ? 'Saving...' : 'Save Changes'}
                                            </button>
                                        </>
                                    ) : (
                                        <button onClick={startEditing} className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-sm font-medium transition-colors border border-slate-700 hover:border-slate-600">
                                            <Edit3 size={16} /> Edit
                                        </button>
                                    )}
                                </div>
                            </div>

                            {/* Metadata Editor (shown in edit mode) */}
                            {editing && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 bg-slate-900/50 border border-slate-800/50 rounded-xl">
                                    {/* Priority */}
                                    <div className="space-y-1.5">
                                        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                                            <Star size={12} />
                                            Priority
                                            <span className="text-slate-600 font-normal">(lower = higher priority)</span>
                                        </label>
                                        <input 
                                            type="number"
                                            min="0"
                                            value={editPriority}
                                            onChange={e => setEditPriority(parseInt(e.target.value) || 0)}
                                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/50 transition-colors"
                                        />
                                    </div>
                                    {/* Disclosure */}
                                    <div className="space-y-1.5">
                                        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                                            <AlertTriangle size={12} />
                                            Disclosure
                                            <span className="text-slate-600 font-normal">(when to recall)</span>
                                        </label>
                                        <input 
                                            type="text"
                                            value={editDisclosure}
                                            onChange={e => setEditDisclosure(e.target.value)}
                                            placeholder="e.g. When I need to remember..."
                                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 transition-colors"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* Content Editor / Viewer */}
                            <div className={clsx(
                                "relative rounded-xl border overflow-hidden transition-all duration-300",
                                editing ? "bg-slate-900 border-indigo-500/50 shadow-[0_0_30px_rgba(99,102,241,0.1)]" : "bg-[#0A0A12]/50 border-slate-800/50"
                            )}>
                                {editing ? (
                                    <textarea 
                                        value={editContent}
                                        onChange={e => setEditContent(e.target.value)}
                                        className="w-full h-96 p-6 bg-transparent text-slate-200 font-mono text-sm leading-relaxed focus:outline-none resize-y"
                                        spellCheck={false}
                                    />
                                ) : (
                                    <div className="p-6 md:p-8 prose prose-invert prose-sm max-w-none">
                                        <pre className="whitespace-pre-wrap font-serif text-slate-300 leading-7">{node.content}</pre>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Children Grid */}
                    {data.children && data.children.length > 0 && (
                        <div className="space-y-4 pt-4">
                            <div className="flex items-center gap-3 text-slate-500">
                                <h2 className="text-xs font-bold uppercase tracking-widest">
                                    {isRoot ? "Memory Clusters" : "Sub-Nodes"}
                                </h2>
                                <div className="h-px flex-1 bg-slate-800/50"></div>
                                <span className="text-xs bg-slate-800/50 px-2 py-0.5 rounded-full">{data.children.length}</span>
                            </div>
                            
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                {data.children.map(child => (
                                    <NodeGridCard 
                                        key={`${child.domain || domain}:${child.path}`} 
                                        node={child}
                                        currentDomain={domain}
                                        onClick={() => navigateTo(child.path, child.domain)} 
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                    
                    {/* Empty State for Children */}
                    {!loading && !data.children?.length && !node && (
                        <div className="flex flex-col items-center justify-center py-20 text-slate-600 gap-4">
                            <Folder size={48} className="opacity-20" />
                            <p className="text-sm">Empty Sector</p>
                        </div>
                    )}
                </div>
            )}
         </div>
      </div>
    </div>
  );
}
