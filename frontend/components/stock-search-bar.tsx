"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import type { StockItem } from "@/lib/types";

export function StockSearchBar({ onSelect }: { onSelect: (stock: StockItem) => void }) {
  const { data: stocks = [] } = useQuery({ queryKey: ["stocks"], queryFn: api.stocks });

  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<StockItem | null>(null);

  const filtered = useMemo(() => {
    if (!search) return stocks.slice(0, 30);
    const q = search.toLowerCase();
    return stocks.filter((s) =>
      s.code.includes(q) || s.name.toLowerCase().includes(q)
    ).slice(0, 30);
  }, [stocks, search]);

  useEffect(() => {
    if (selected) onSelect(selected);
  }, [selected]);

  return (
    <div className="relative w-80">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
      <input
        type="text"
        value={selected ? selected.label : search}
        onFocus={() => { setOpen(true); if (selected) setSearch(""); }}
        onChange={(e) => { setSearch(e.target.value); setSelected(null); setOpen(true); }}
        placeholder="输入代码或名称搜索…"
        className="w-full bg-zinc-950 border border-zinc-800 rounded-md pl-9 pr-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-10 mt-1 w-full max-h-60 overflow-auto bg-zinc-950 border border-zinc-800 rounded-md shadow-lg">
          {filtered.map((s) => (
            <button
              key={s.code}
              onClick={() => { setSelected(s); setOpen(false); setSearch(""); }}
              className="w-full text-left px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
