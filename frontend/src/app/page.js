'use client';

import { useState, useEffect, useRef } from 'react';

// ── Constants ──────────────────────────────────────────────────────────────
const API_BASE = '/api';

const DEVICE_CATEGORIES = [
  'Blood Collection', 'Cardiovascular', 'Neurological', 'Orthopedic',
  'Dermatology', 'Ophthalmology', 'Pulmonary', 'Endocrinology',
  'Radiology', 'Wound Care', 'Sleep Medicine', 'Audiology',
  'General Medical', 'Gastroenterology', 'Dental', 'Urology', 'Other',
];

const INTENDED_USES = [
  'Blood collection', 'Blood specimen collection', 'IV administration',
  'In vitro diagnostic testing', 'Diagnosis', 'Monitoring', 'Treatment',
  'Screening', 'Adjunctive', 'Decision support', 'Measurement',
  'Documentation', 'Navigation/Guidance', 'Other',
];

const POPULATIONS = [
  'General population', 'Adults (18+)', 'Adults and pediatric',
  'Adults and adolescent', 'Pediatric', 'Neonatal', 'All ages',
  'Specific weight/age range', 'Other',
];

const SETTINGS = [
  'Healthcare facilities', 'Hospital', 'Outpatient', 'Clinical laboratory',
  'Primary care', 'Specialty clinic', 'Operating room', 'Emergency department',
  'Home use', 'Hospital and outpatient', 'Hospital, outpatient, and home', 'Other',
];

const USER_TYPES = [
  'Trained healthcare professional', 'Healthcare professional (venipuncture)',
  'Medical professional', 'Trained specialist', 'Patient (self-use)',
  'Over-the-counter (OTC)', 'Under HCP direction', 'Other',
];

const TECH_TYPES = [
  'Needle/sharp device', 'Collection set (winged/butterfly)',
  'Collection tube', 'Safety device', 'Needle-free device',
  'Software (SaMD)', 'Hardware device', 'AI/ML-based', 'Implantable',
  'Wearable', 'In-vitro diagnostic', 'Combination product', 'Electromechanical',
  'Imaging system', 'Other',
];

// ── API Client ─────────────────────────────────────────────────────────────
async function apiRetrieve(deviceInput, topK = 3) {
  const res = await fetch(`${API_BASE}/retrieve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_input: deviceInput, top_k: topK }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

async function apiGenerate(deviceInput, topK = 3) {
  const res = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_input: deviceInput, top_k: topK }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

// ── Custom Select Component ────────────────────────────────────────────────
function SelectField({ label, value, onChange, options, required, placeholder }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <label className="block text-sm font-medium text-stone-700 mb-1.5">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <div
        className={`relative w-full px-3.5 py-2.5 border rounded-lg bg-white cursor-pointer flex items-center justify-between transition-colors text-sm ${
          open ? 'border-brand-500 ring-2 ring-brand-50' : 'border-stone-200 hover:border-stone-300'
        }`}
        onClick={() => setOpen(!open)}
      >
        <span className={value ? 'text-stone-900' : 'text-stone-400'}>
          {value || placeholder || 'Select...'}
        </span>
        <svg className={`w-4 h-4 text-stone-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
          <polyline points="6 9 12 15 18 9" />
        </svg>
        {open && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-stone-200 rounded-lg shadow-lg z-50 max-h-56 overflow-y-auto select-dropdown-anim">
            {options.map((opt) => (
              <div
                key={opt}
                className={`px-3.5 py-2 text-sm cursor-pointer transition-colors ${
                  value === opt ? 'bg-brand-50 text-brand-600 font-medium' : 'hover:bg-stone-50'
                }`}
                onClick={(e) => { e.stopPropagation(); onChange(opt); setOpen(false); }}
              >
                {opt}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Header ─────────────────────────────────────────────────────────────────
function Header({ onReset, step }) {
  return (
    <header className="bg-white border-b border-stone-200 sticky top-0 z-40">
      <div className="max-w-5xl mx-auto px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 cursor-pointer" onClick={onReset}>
          <div className="w-8 h-8 bg-brand-500 rounded-lg flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <span className="font-display text-lg font-bold">CompliantAI</span>
          <span className="font-mono text-[10px] font-medium text-brand-500 bg-brand-50 px-2 py-0.5 rounded">510(k)</span>
        </div>
        <div className="flex items-center gap-2 text-xs font-medium">
          <span className={step >= 1 ? 'text-brand-500' : 'text-stone-400'}>Input</span>
          <span className="text-stone-300">›</span>
          <span className={step >= 2 ? 'text-brand-500' : 'text-stone-400'}>Match</span>
          <span className="text-stone-300">›</span>
          <span className={step >= 3 ? 'text-brand-500' : 'text-stone-400'}>Generate</span>
        </div>
      </div>
    </header>
  );
}

// ── Step Dots ──────────────────────────────────────────────────────────────
function StepDots({ current }) {
  return (
    <div className="flex items-center justify-center gap-0 mb-6">
      {[1, 2, 3].map((s, i) => (
        <div key={s} className="flex items-center">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold border-2 transition-all ${
            s < current ? 'border-green-500 bg-green-50 text-green-600' :
            s === current ? 'border-brand-500 bg-brand-500 text-white shadow-sm shadow-brand-200' :
            'border-stone-200 bg-white text-stone-400'
          }`}>
            {s < current ? '✓' : s}
          </div>
          {i < 2 && <div className={`w-16 h-0.5 ${s < current ? 'bg-green-400' : 'bg-stone-200'}`} />}
        </div>
      ))}
    </div>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────
export default function Home() {
  const [step, setStep] = useState(0);
  const [formData, setFormData] = useState({
    device_name: '',
    device_category: '',
    regulation_number: '',
    product_code: '',
    intended_use: '',
    target_population: '',
    clinical_setting: '',
    user_type: '',
    technology_type: '',
    limitations: '',
    predicate_k_number: '',
    openai_api_key: '',
  });
  const [predicates, setPredicates] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState('');

  const update = (field, value) => setFormData(prev => ({ ...prev, [field]: value }));

  const canProceed = formData.device_name && formData.device_category &&
    formData.intended_use && formData.target_population &&
    formData.clinical_setting && formData.user_type && formData.technology_type;

  // Step 1 → 2: Retrieve predicates
  const handleRetrieve = async () => {
    if (!formData.openai_api_key) {
      setError('Please enter your OpenAI API key.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const data = await apiRetrieve(formData);
      setPredicates(data.predicates);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Step 2 → 3: Generate
  const handleGenerate = async () => {
    setError('');
    setLoading(true);
    setStep(3);
    try {
      const data = await apiGenerate(formData);
      setResult(data);
      setEditText(data.indications_text);
    } catch (err) {
      setError(err.message);
      setStep(2);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(editMode ? editText : result?.indications_text || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleReset = () => {
    setStep(0);
    setFormData({
      device_name: '', device_category: '', regulation_number: '', product_code: '',
      intended_use: '', target_population: '', clinical_setting: '', user_type: '',
      technology_type: '', limitations: '', predicate_k_number: '',
      openai_api_key: formData.openai_api_key, // Preserve API key
    });
    setPredicates([]);
    setResult(null);
    setError('');
    setEditMode(false);
    setEditText('');
  };

  // ── LANDING ──────────────────────────────────────────────────────────────
  if (step === 0) {
    return (
      <div className="min-h-screen flex flex-col items-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-brand-50/40 via-transparent to-transparent pointer-events-none" />

        <nav className="w-full max-w-5xl px-8 pt-7 relative z-10">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 bg-brand-500 rounded-lg flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </div>
            <span className="font-display text-xl font-bold">CompliantAI</span>
            <span className="font-mono text-[10px] font-medium text-brand-500 bg-brand-50 px-2 py-0.5 rounded tracking-wider">510(k)</span>
          </div>
        </nav>

        <div className="flex-1 flex flex-col items-center justify-center text-center px-8 max-w-3xl relative z-10 -mt-8">
          <div className="font-mono text-[11px] tracking-[2.5px] text-brand-500 font-medium mb-5">
            RAG-POWERED REGULATORY DRAFTING
          </div>
          <h1 className="font-display text-5xl md:text-[52px] font-bold leading-[1.1] tracking-tight mb-5">
            Indications for Use<br />
            <span className="text-brand-500">Generated with Precision</span>
          </h1>
          <p className="text-stone-500 text-[17px] leading-relaxed mb-9 max-w-lg">
            Draft FDA-compliant Indications for Use sections in seconds.
            Grounded by cleared predicate submissions via semantic search. Built for regulatory professionals.
          </p>
          <button
            className="bg-brand-500 hover:bg-brand-600 text-white px-8 py-3.5 rounded-xl font-semibold text-[15px] transition-colors flex items-center gap-2.5"
            onClick={() => setStep(1)}
          >
            Start Drafting
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
            </svg>
          </button>

          <div className="flex items-center gap-7 mt-12">
            {[
              ['20', 'Cleared Predicates'],
              ['FAISS', 'Vector Search'],
              ['GPT-4.1', 'Generation'],
            ].map(([val, label], i) => (
              <div key={label} className="flex items-center gap-7">
                {i > 0 && <div className="w-px h-8 bg-stone-200" />}
                <div className="text-center">
                  <div className="font-mono text-xl font-medium">{val}</div>
                  <div className="text-xs text-stone-400 mt-0.5">{label}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex gap-5 px-8 pb-14 max-w-4xl w-full relative z-10">
          {[
            ['01', 'Structured Intake', 'Answer targeted questions about your device'],
            ['02', 'Semantic Matching', 'FAISS cosine similarity finds closest predicates'],
            ['03', 'AI Generation', 'GPT-4.1 produces regulatory-grade language'],
          ].map(([num, title, desc]) => (
            <div key={num} className="flex-1 bg-white border border-stone-200 rounded-xl p-6 hover:border-brand-400 transition-colors">
              <span className="font-mono text-[11px] text-brand-500 tracking-wider">{num}</span>
              <h3 className="font-display text-base font-semibold mt-2.5 mb-1">{title}</h3>
              <p className="text-sm text-stone-500 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── FORM (Step 1) ────────────────────────────────────────────────────────
  if (step === 1) {
    return (
      <div className="min-h-screen page-enter">
        <Header onReset={handleReset} step={1} />
        <div className="max-w-4xl mx-auto px-6 py-10">
          <StepDots current={1} />
          <div className="text-center mb-8">
            <h2 className="font-display text-2xl font-bold">Device Information</h2>
            <p className="text-stone-500 text-sm mt-1">Provide details about your medical device. Required fields are marked with an asterisk.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-stone-700 mb-1.5">
                Device Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text" value={formData.device_name}
                onChange={e => update('device_name', e.target.value)}
                placeholder="e.g., SafeGuard Push Button Blood Collection Set"
                className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none transition-colors"
              />
            </div>

            <SelectField label="Device Category" value={formData.device_category} onChange={v => update('device_category', v)} options={DEVICE_CATEGORIES} required placeholder="Select category" />
            <SelectField label="Technology Type" value={formData.technology_type} onChange={v => update('technology_type', v)} options={TECH_TYPES} required placeholder="Select type" />
            <SelectField label="Intended Use" value={formData.intended_use} onChange={v => update('intended_use', v)} options={INTENDED_USES} required placeholder="Select intended use" />
            <SelectField label="Target Population" value={formData.target_population} onChange={v => update('target_population', v)} options={POPULATIONS} required placeholder="Select population" />
            <SelectField label="Clinical Setting" value={formData.clinical_setting} onChange={v => update('clinical_setting', v)} options={SETTINGS} required placeholder="Select setting" />
            <SelectField label="User Type" value={formData.user_type} onChange={v => update('user_type', v)} options={USER_TYPES} required placeholder="Select user type" />

            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1.5">Regulation Number</label>
              <input type="text" value={formData.regulation_number} onChange={e => update('regulation_number', e.target.value)}
                placeholder="e.g., 21 CFR 880.5570" className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none" />
            </div>
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1.5">Product Code</label>
              <input type="text" value={formData.product_code} onChange={e => update('product_code', e.target.value)}
                placeholder="e.g., FMF" className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none" />
            </div>
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1.5">Predicate K-Number</label>
              <input type="text" value={formData.predicate_k_number} onChange={e => update('predicate_k_number', e.target.value)}
                placeholder="e.g., K220212" className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none" />
            </div>
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1.5">
                OpenAI API Key <span className="text-red-500">*</span>
              </label>
              <input type="password" value={formData.openai_api_key} onChange={e => { update('openai_api_key', e.target.value); setError(''); }}
                placeholder="sk-..." className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm font-mono focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none tracking-wider" />
              <p className="text-[11px] text-stone-400 mt-1">Used for embeddings + generation. Sent directly to OpenAI, never stored.</p>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-stone-700 mb-1.5">Limitations or Exclusions</label>
              <textarea value={formData.limitations} onChange={e => update('limitations', e.target.value)}
                placeholder="e.g., Not intended for infusion, IV administration, or transfusion. Not intended for use as a diagnostic device."
                rows={3} className="w-full px-3.5 py-2.5 border border-stone-200 rounded-lg text-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-50 outline-none resize-y" />
            </div>
          </div>

          {error && (
            <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              {error}
            </div>
          )}

          <div className="flex justify-between items-center mt-8">
            <button className="px-5 py-2.5 border border-stone-200 rounded-lg text-sm font-medium hover:bg-stone-50 transition-colors flex items-center gap-2" onClick={() => setStep(0)}>
              ← Back
            </button>
            <button
              className="bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed text-white px-6 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2"
              onClick={handleRetrieve}
              disabled={!canProceed || !formData.openai_api_key || loading}
            >
              {loading ? (
                <><div className="spinner w-4 h-4" /> Finding Predicates...</>
              ) : (
                <>Match Predicates →</>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── REVIEW (Step 2) ──────────────────────────────────────────────────────
  if (step === 2) {
    return (
      <div className="min-h-screen page-enter">
        <Header onReset={handleReset} step={2} />
        <div className="max-w-4xl mx-auto px-6 py-10">
          <StepDots current={2} />
          <div className="text-center mb-8">
            <h2 className="font-display text-2xl font-bold">Predicate Matching</h2>
            <p className="text-stone-500 text-sm mt-1">
              FAISS cosine similarity found the closest cleared 510(k) submissions from the vector index.
            </p>
          </div>

          {/* Device Summary */}
          <div className="bg-white border border-stone-200 rounded-xl p-5 mb-6">
            <h3 className="font-display text-sm font-semibold text-stone-700 mb-3 flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              Your Device
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                ['Device', formData.device_name],
                ['Category', formData.device_category],
                ['Technology', formData.technology_type],
                ['Intended Use', formData.intended_use],
                ['Population', formData.target_population],
                ['Setting', formData.clinical_setting],
                ['User', formData.user_type],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="text-[10px] uppercase tracking-wider text-stone-400 font-medium">{k}</div>
                  <div className="text-sm font-medium text-stone-800 mt-0.5">{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Predicates */}
          <h3 className="font-display text-sm font-semibold text-stone-700 mb-3 flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
            Top {predicates.length} Predicate Matches (via FAISS Cosine Similarity)
          </h3>

          {predicates.map((p, i) => (
            <div key={i} className="bg-white border border-stone-200 rounded-xl p-5 mb-3 hover:border-brand-400 transition-colors">
              <div className="flex items-start gap-3 mb-3">
                <div className="w-8 h-8 bg-brand-50 text-brand-600 rounded-lg flex items-center justify-center font-mono text-xs font-semibold shrink-0">
                  #{i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-sm text-stone-800 truncate">{p.device_name}</div>
                  <div className="text-xs text-stone-400 font-mono mt-0.5">{p.k_number || 'N/A'} · {p.filename}</div>
                </div>
                <div className="font-mono text-xs font-medium text-brand-600 bg-brand-50 px-2.5 py-1 rounded-full whitespace-nowrap">
                  {(p.similarity_score * 100).toFixed(1)}% similarity
                </div>
              </div>
              <div className="text-[13px] text-stone-500 leading-relaxed pl-11 border-t border-stone-100 pt-3">
                {p.indications_text}
              </div>
            </div>
          ))}

          {error && (
            <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              {error}
            </div>
          )}

          <div className="flex justify-between items-center mt-8">
            <button className="px-5 py-2.5 border border-stone-200 rounded-lg text-sm font-medium hover:bg-stone-50 transition-colors" onClick={() => setStep(1)}>
              ← Edit Inputs
            </button>
            <button
              className="bg-brand-500 hover:bg-brand-600 text-white px-6 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2 shadow-md shadow-brand-500/20"
              onClick={handleGenerate}
              disabled={loading}
            >
              {loading ? (
                <><div className="spinner w-4 h-4" /> Generating...</>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>
                  Generate with GPT-4.1
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── RESULT (Step 3) ──────────────────────────────────────────────────────
  if (step === 3) {
    return (
      <div className="min-h-screen page-enter">
        <Header onReset={handleReset} step={3} />
        <div className="max-w-4xl mx-auto px-6 py-10">
          <StepDots current={3} />
          <div className="text-center mb-8">
            <h2 className="font-display text-2xl font-bold">Generated Output</h2>
            <p className="text-stone-500 text-sm mt-1">Your FDA-style Indications for Use section is ready for review.</p>
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <div className="spinner w-10 h-10" />
              <div className="font-medium text-stone-700">Generating with OpenAI GPT-4.1...</div>
              <div className="text-sm text-stone-400">Embedding query → FAISS retrieval → Prompt construction → Generation → Validation</div>
            </div>
          ) : result ? (
            <>
              {/* Output */}
              <div className="bg-white border border-stone-200 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 bg-stone-50 border-b border-stone-200">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[10px] tracking-widest text-stone-400 font-medium">INDICATIONS FOR USE</span>
                    <span className="text-[10px] text-stone-400">via {result.model_used} · {result.generation_time_ms}ms</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => { setEditMode(!editMode); if (!editMode) setEditText(result.indications_text); }}
                      className="px-3 py-1 border border-stone-200 rounded text-xs font-medium text-stone-500 hover:bg-white transition-colors">
                      {editMode ? 'View' : 'Edit'}
                    </button>
                    <button onClick={handleCopy}
                      className="px-3 py-1 border border-stone-200 rounded text-xs font-medium text-stone-500 hover:bg-white transition-colors flex items-center gap-1.5">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                      {copied ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
                {editMode ? (
                  <textarea
                    className="w-full p-6 text-[15px] leading-7 text-stone-800 resize-y outline-none min-h-[200px] bg-amber-50/30"
                    value={editText}
                    onChange={e => setEditText(e.target.value)}
                    rows={10}
                  />
                ) : (
                  <div className="p-6 text-[15px] leading-7 text-stone-800">
                    {result.indications_text.split('\n\n').map((para, i) => (
                      <p key={i} className="mb-4 last:mb-0">{para}</p>
                    ))}
                  </div>
                )}
              </div>

              {/* Validation */}
              <div className="bg-white border border-stone-200 rounded-xl p-5 mt-5">
                <h3 className="font-display text-sm font-semibold mb-3 flex items-center gap-2">
                  {result.validation.pass ? (
                    <span className="text-green-600 flex items-center gap-1.5">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      Validation Passed
                    </span>
                  ) : (
                    <span className="text-amber-600 flex items-center gap-1.5">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                      Issues Found — Risk: {result.validation.risk_level}
                    </span>
                  )}
                </h3>

                {(result.validation.hard_constraint_issues?.length > 0 || result.validation.ai_issues?.length > 0) && (
                  <div className="mb-4 space-y-1.5">
                    {[...(result.validation.hard_constraint_issues || []), ...(result.validation.ai_issues || [])].map((issue, i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-700 rounded text-xs">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                        {issue}
                      </div>
                    ))}
                  </div>
                )}

                {result.validation.suggestions?.length > 0 && (
                  <div className="mb-4 space-y-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-stone-400 font-medium mb-1">Suggestions</div>
                    {result.validation.suggestions.map((s, i) => (
                      <div key={i} className="text-xs text-stone-600 pl-3 border-l-2 border-brand-200">{s}</div>
                    ))}
                  </div>
                )}

                <div className="text-[10px] uppercase tracking-wider text-stone-400 font-medium mb-2">Quality Checks</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
                  {[
                    'No promotional language',
                    'No superiority claims',
                    'No banned terminology',
                    'Device type defined',
                    'Population specified',
                    'Clinical setting stated',
                    'User qualification included',
                  ].map(c => (
                    <div key={c} className="flex items-center gap-1.5 text-xs text-green-600 py-0.5">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      {c}
                    </div>
                  ))}
                </div>
              </div>

              {/* Predicates used */}
              <details className="mt-5 bg-white border border-stone-200 rounded-xl">
                <summary className="px-5 py-3 text-sm font-medium text-stone-600 cursor-pointer hover:text-stone-800">
                  View predicates used for generation ({result.predicates_used?.length || 0} matches)
                </summary>
                <div className="px-5 pb-4 space-y-3">
                  {result.predicates_used?.map((p, i) => (
                    <div key={i} className="border-t border-stone-100 pt-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">#{i+1}</span>
                        <span className="text-sm font-medium">{p.device_name}</span>
                        <span className="font-mono text-xs text-stone-400">{p.k_number}</span>
                        <span className="font-mono text-[10px] text-brand-600 ml-auto">{(p.similarity_score * 100).toFixed(1)}%</span>
                      </div>
                      <p className="text-xs text-stone-400 mt-1.5 leading-relaxed">{p.indications_text}</p>
                    </div>
                  ))}
                </div>
              </details>

              {/* Actions */}
              <div className="flex justify-between items-center mt-8">
                <button className="px-5 py-2.5 border border-stone-200 rounded-lg text-sm font-medium hover:bg-stone-50 transition-colors" onClick={() => setStep(2)}>
                  ← Back
                </button>
                <div className="flex gap-3">
                  <button className="px-5 py-2.5 border border-stone-200 rounded-lg text-sm font-medium hover:bg-stone-50 transition-colors flex items-center gap-2" onClick={() => { setResult(null); handleGenerate(); }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>
                    Regenerate
                  </button>
                  <button className="bg-brand-500 hover:bg-brand-600 text-white px-6 py-2.5 rounded-lg text-sm font-semibold transition-colors" onClick={handleReset}>
                    New Device
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>
    );
  }

  return null;
}
