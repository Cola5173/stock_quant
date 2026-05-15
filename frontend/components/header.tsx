export function Header() {
  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-6 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-2">
        <span className="text-xl font-bold text-zinc-100">Cola Quant</span>
        <span className="text-xs text-zinc-500">A 股量化回测平台</span>
      </div>
    </header>
  );
}
