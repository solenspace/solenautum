export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <main className="grid min-h-dvh place-items-center px-6">
      <div className="w-full max-w-sm">
        <p className="mb-6 text-sm text-muted-foreground">Scrape websites in parallel.</p>
        {children}
      </div>
    </main>
  );
}
