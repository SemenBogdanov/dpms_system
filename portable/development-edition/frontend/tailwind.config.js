/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: '#6B8DE8',
          light: '#93AFF8',
          lighter: '#E8EFFE',
          dark: '#4E70C8',
        },
      },
    },
  },
  plugins: [],
}
