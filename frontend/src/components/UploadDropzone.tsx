import { useState } from "react";

interface UploadDropzoneProps {
  disabled?: boolean;
  onFile: (file: File) => void;
}

export function UploadDropzone({ disabled = false, onFile }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  function takeFile(fileList: FileList | null) {
    const file = fileList?.[0];
    if (file) {
      onFile(file);
    }
  }

  return (
    <label
      className={`block cursor-pointer rounded-xl border border-dashed px-6 py-10 text-center transition ${
        isDragging ? "border-cyan-400 bg-cyan-400/10" : "border-slate-700 bg-slate-900"
      } ${disabled ? "pointer-events-none opacity-60" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        takeFile(event.dataTransfer.files);
      }}
    >
      <input
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        disabled={disabled}
        onChange={(event) => takeFile(event.target.files)}
      />
      <p className="text-sm font-medium text-slate-100">Drop a fund-universe CSV here, or click to browse</p>
      <p className="mt-2 text-xs text-slate-400">
        One long-form file. Required columns: fund_id, fund_name, strategy, period, net_return,
        liquidity_frequency, notice_days, lockup_months, mgmt_fee_bps, perf_fee_bps, notes.
      </p>
    </label>
  );
}
