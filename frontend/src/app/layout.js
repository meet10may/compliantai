import './globals.css';

export const metadata = {
  title: 'CompliantAI — AI-Powered Indications for Use Generator',
  description: 'Generate FDA-compliant Indications for Use sections for 510(k) submissions using RAG-powered AI.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="bg-stone-50 text-stone-900 min-h-screen">
        {children}
      </body>
    </html>
  );
}
