/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#E8F0EC',
          100: '#D1E1D9',
          200: '#A3C3B3',
          300: '#75A58D',
          400: '#478767',
          500: '#1B4D3E',
          600: '#153D31',
          700: '#102E25',
          800: '#0B1F19',
          900: '#050F0C',
        },
      },
      fontFamily: {
        display: ['"Source Serif 4"', 'Georgia', 'serif'],
        body: ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
};
