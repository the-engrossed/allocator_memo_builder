interface StrategyChipsProps {
  options: string[];
  selected: string[];
  universe: string[];
  disabled?: boolean;
  onToggle: (strategy: string) => void;
}

export function StrategyChips({
  options,
  selected,
  universe,
  disabled = false,
  onToggle,
}: StrategyChipsProps) {
  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-2">
        {options.map((strategy) => {
          const position = selected.indexOf(strategy);
          const isSelected = position >= 0;
          const inUniverse = universe.includes(strategy);
          return (
            <li key={strategy}>
              <button
                type="button"
                disabled={disabled}
                aria-pressed={isSelected}
                onClick={() => onToggle(strategy)}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${
                  isSelected
                    ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-100"
                    : "border-slate-700 text-slate-300 hover:border-slate-500"
                }`}
              >
                {isSelected && (
                  <span className="font-mono text-xs text-cyan-300">{position + 1}</span>
                )}
                <span>{strategy}</span>
                {!inUniverse && (
                  <span className="text-[10px] uppercase tracking-wide text-slate-500">
                    not in upload
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-slate-500">
        Selection order is preserved and saved as shown. Strategies marked “not in upload” are
        allowed but no fund in this universe reports them.
      </p>
    </div>
  );
}
