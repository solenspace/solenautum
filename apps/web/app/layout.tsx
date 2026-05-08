import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { I18nProvider } from "@/shared/i18n";
import { THEME_HYDRATION_SCRIPT, ThemeProvider } from "@/shared/theme";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Autumn",
  description: "Concurrent AI scraping agent.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable}`}
        suppressHydrationWarning
      >
        <head>
          {/* Apply the persisted theme class on `<html>` before React
              hydrates so a dark-mode user does not see a light flash.
              The script body is a constant string we control (see
              `THEME_HYDRATION_SCRIPT` in `shared/theme/index.tsx`); no
              user input flows through this path. */}
          {/* biome-ignore lint/security/noDangerouslySetInnerHtml: known-safe constant script for theme hydration */}
          <script dangerouslySetInnerHTML={{ __html: THEME_HYDRATION_SCRIPT }} />
        </head>
        <body>
          <ThemeProvider>
            <I18nProvider>
              <TooltipProvider>{children}</TooltipProvider>
            </I18nProvider>
          </ThemeProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
