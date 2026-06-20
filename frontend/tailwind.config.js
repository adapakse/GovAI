/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        dark:   '#0D1B2A',
        navy:   '#1B355E',
        blue:   '#1E6FBF',
        teal:   '#00B4D8',
        mgray:  '#CBD5E1',
        lgray:  '#F0F4F8',
        govred: '#C0392B',
      },
    },
  },
  plugins: [],
};
