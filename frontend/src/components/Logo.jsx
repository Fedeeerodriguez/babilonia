/**
 * Logo Babilonia — wordmark "Babilonia" en cobalt + isotipo opcional.
 * Para el isotipo real (PNG de la marca) usar <img src="/logo-iso.png" />
 * en `public/`. Acá un fallback tipográfico.
 */
export default function Logo({ size = 'md', tagline = false, color = 'cobalt', className = '' }) {
  const sizes = {
    xs: { txt: 'text-base', tag: 'text-[8px]' },
    sm: { txt: 'text-xl', tag: 'text-[9px]' },
    md: { txt: 'text-2xl', tag: 'text-[10px]' },
    lg: { txt: 'text-5xl', tag: 'text-xs' },
    xl: { txt: 'text-7xl', tag: 'text-sm' },
  }
  const s = sizes[size]
  const colors = {
    cobalt: 'text-cobalt',
    deep: 'text-deep',
    bone: 'text-bone',
    white: 'text-white',
  }

  return (
    <div className={`inline-flex flex-col leading-none ${className}`}>
      <div className={`font-display font-bold tracking-tightest ${colors[color]} ${s.txt}`}>
        Babilonia
      </div>
      {tagline && (
        <div className={`${s.tag} font-medium tracking-[0.18em] uppercase mt-1.5 ${color === 'cobalt' ? 'text-deep/70' : 'text-bone/60'}`}>
          Tomi · Métricas WATI
        </div>
      )}
    </div>
  )
}
