/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Wyłącza client-side Router Cache — bez tego powrót do wcześniej odwiedzonej
  // strony (np. Agenci, Pulpit) w ciągu ~30s potrafi pokazać dane sprzed edycji,
  // bo Next.js podaje zbuforowany widok zamiast ponownie zamontować komponent.
  experimental: {
    staleTimes: { dynamic: 0, static: 0 },
  },
};

module.exports = nextConfig;
