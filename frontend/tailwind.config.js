/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Paleta Babilonia (Cobalt + Deep Cobalt)
        cobalt: {
          DEFAULT: '#2D76B2',
          50: '#F1F6FB',
          100: '#DCE9F4',
          200: '#B5D1E7',
          300: '#85B3D5',
          400: '#5491C2',
          500: '#2D76B2',
          600: '#245E8E',
          700: '#1C496F',
          800: '#163A58',
          900: '#0F2740',
        },
        deep: {
          DEFAULT: '#2E3A5F',
          50: '#EEF0F5',
          100: '#D8DCE8',
          200: '#B0B7CD',
          300: '#7E88AC',
          400: '#525E89',
          500: '#2E3A5F',
          600: '#262F4D',
          700: '#1E253D',
          800: '#161B2C',
          900: '#0E121C',
        },
        bone: {
          DEFAULT: '#EEEAE3',
          50: '#FAFAF8',
          100: '#F5F2EC',
          200: '#EEEAE3',
          300: '#E5E0D6',
          400: '#D4CCBC',
        },
        bg: '#FAFAF8',
        surface: '#FFFFFF',
        surface2: '#F5F2EC',
        border: '#E5E0D6',
        text: '#2E3A5F',
        muted: '#6B7280',
        accent: '#2D76B2',
        success: '#2F7D5B',
        warn: '#B45309',
        danger: '#B33A3A',
      },
      fontFamily: {
        display: ['"SF Pro Display"', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'Helvetica', 'Arial', 'sans-serif'],
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Helvetica', 'Arial', 'sans-serif'],
      },
      letterSpacing: { tightest: '-0.04em', tighter: '-0.025em' },
      boxShadow: {
        'soft': '0 1px 2px rgba(46, 58, 95, 0.04), 0 4px 12px rgba(46, 58, 95, 0.04)',
        'card': '0 1px 3px rgba(46, 58, 95, 0.06), 0 8px 24px rgba(46, 58, 95, 0.06)',
        'lift': '0 4px 8px rgba(46, 58, 95, 0.08), 0 16px 40px rgba(46, 58, 95, 0.08)',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'slide-up': 'slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp: { '0%': { transform: 'translateY(24px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
      },
    },
  },
  plugins: [],
}
