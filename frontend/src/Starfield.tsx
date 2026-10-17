import { useEffect, useRef, useState } from 'react';

type Star = {x: number, y: number, r: number, a: number, layer: number, twinkle: boolean, phase: number, speed: number, glow: boolean};
const PARALLAX = [0.02, 0.04, 0.07];
const AREA_PER_STAR = 2500;
const SEED = 20261017;

/** Small deterministic generator so the sky is the same on every load. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeStars(width: number, height: number): Star[] {
  const rand = mulberry32(SEED);
  const count = Math.round((width * height) / AREA_PER_STAR);
  const stars: Star[] = [];
  for (let i = 0; i < count; i++) {
    const roll = rand();
    const layer = roll < 0.62 ? 0 : roll < 0.93 ? 1 : 2;
    stars.push({
      x: rand() * width, y: rand() * height * 1.0,
      r: layer === 0 ? 0.35 + rand() * 0.3 : layer === 1 ? 0.6 + rand() * 0.35 : 0.95 + rand() * 0.55,
      a: layer === 0 ? 0.25 + rand() * 0.2 : layer === 1 ? 0.45 + rand() * 0.25 : 0.75 + rand() * 0.25,
      layer, twinkle: rand() < 0.15, phase: rand() * Math.PI * 2, speed: 0.6 + rand() * 1.2, glow: layer === 2,
    });
  }
  return stars;
}

function currentTheme() {return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';}

/** Fixed full-viewport starfield behind the console, drawn only in the dark theme. */
export function Starfield() {
  const ref = useRef<HTMLCanvasElement>(null);
  const [theme, setTheme] = useState(currentTheme);
  useEffect(() => {
    const update = () => setTheme(currentTheme());
    window.addEventListener('og-theme', update);
    return () => window.removeEventListener('og-theme', update);
  }, []);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || theme !== 'dark') return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let stars: Star[] = [];
    let width = 0, height = 0, dpr = 1, frame = 0, resizeTimer = 0;
    let scrollY = window.scrollY;

    function draw(now: number) {
      const ctx = context!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const still = reduced.matches;
      for (const star of stars) {
        const drift = still ? 0 : scrollY * PARALLAX[star.layer];
        const y = (((star.y - drift) % height) + height) % height;
        let alpha = star.a;
        if (star.twinkle && !still) alpha *= 0.55 + 0.45 * Math.sin(now / 1000 * star.speed + star.phase);
        if (star.glow) {
          const glow = ctx.createRadialGradient(star.x, y, 0, star.x, y, star.r * 5);
          glow.addColorStop(0, `rgba(190, 215, 255, ${alpha * 0.45})`);
          glow.addColorStop(1, 'rgba(190, 215, 255, 0)');
          ctx.fillStyle = glow;
          ctx.fillRect(star.x - star.r * 5, y - star.r * 5, star.r * 10, star.r * 10);
        }
        ctx.fillStyle = `rgba(${star.layer === 2 ? '225, 238, 255' : '205, 222, 250'}, ${alpha})`;
        ctx.beginPath();
        ctx.arc(star.x, y, star.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    function loop(now: number) {
      draw(now);
      frame = requestAnimationFrame(loop);
    }
    function start() {
      cancelAnimationFrame(frame);
      if (reduced.matches || document.hidden) {draw(performance.now()); return;}
      frame = requestAnimationFrame(loop);
    }
    function resize() {
      dpr = window.devicePixelRatio || 1;
      width = window.innerWidth; height = window.innerHeight;
      canvas!.width = Math.round(width * dpr); canvas!.height = Math.round(height * dpr);
      canvas!.style.width = `${width}px`; canvas!.style.height = `${height}px`;
      stars = makeStars(width, height);
      draw(performance.now());
    }
    const onResize = () => {window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(() => {resize(); start();}, 150);};
    const onScroll = () => {scrollY = window.scrollY; if (reduced.matches || document.hidden) draw(performance.now());};
    const onVisibility = () => start();
    resize(); start();
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, {passive: true});
    document.addEventListener('visibilitychange', onVisibility);
    reduced.addEventListener('change', onVisibility);
    return () => {
      cancelAnimationFrame(frame); window.clearTimeout(resizeTimer);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onScroll);
      document.removeEventListener('visibilitychange', onVisibility);
      reduced.removeEventListener('change', onVisibility);
    };
  }, [theme]);

  if (theme !== 'dark') return null;
  return <canvas ref={ref} className="starfield" aria-hidden="true"/>;
}
