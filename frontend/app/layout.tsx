import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Font files live in the repo (Geist, SIL OFL, see fonts/OFL.txt), so neither
// the build nor the browser ever calls Google Fonts. Geist carries UI text and
// display headings; Geist Mono carries quotes and code. Both are variable fonts.
const geistSans = localFont({
  src: "./fonts/geist-latin.woff2",
  variable: "--font-geist-sans",
  weight: "100 900",
});

const geistMono = localFont({
  src: "./fonts/geist-mono-latin.woff2",
  variable: "--font-geist-mono",
  weight: "100 900",
});

// Runs before first paint so the page never flashes the wrong theme: the
// saved choice from the theme toggle, else the OS setting.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}})()`;

export const metadata: Metadata = {
  title: "Paper Trail",
  description: "An AI-powered research workspace for AI/ML papers.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // data-theme is set by THEME_SCRIPT before React hydrates.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
