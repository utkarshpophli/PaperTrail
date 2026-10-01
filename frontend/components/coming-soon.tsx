export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-24 text-center">
      <h1 className="text-h1 font-display font-semibold text-foreground">{title}</h1>
      <p className="text-body text-muted-foreground">Coming soon.</p>
    </div>
  );
}
