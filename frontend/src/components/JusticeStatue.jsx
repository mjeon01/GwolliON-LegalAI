import { useEffect, useRef, useState } from 'react';
import statueSrc from '../assets/statue.webp';
import stemSrc from '../assets/stem.webp';
import beamSrc from '../assets/beam.webp';
import panLSrc from '../assets/panL.webp';
import panRSrc from '../assets/panR.webp';
import L from '../assets/layout.json';

/*
 * Layered statue: the bronze figure is a single static plate; the scales are
 * four cut-out layers (stem, beam, left pan, right pan) driven by a small
 * physics model, all in the same 670×720 design space.
 *
 *   φ  – whole assembly sways from the hand (light secondary motion)
 *   θ  – beam tilts about its fulcrum (main motion, spring + inertia)
 *   ψ  – each pan is a true gravity pendulum hanging from its beam tip,
 *        driven by the tip's acceleration, so it lags and settles naturally
 */

const DEG = Math.PI / 180;
const HAND = { x: L.stem.x + L.stem.w / 2, y: L.stem.y + 2 }; // assembly pivot
const FULCRUM = { x: 190.5, y: L.beam.y };                     // beam hinge
const BEAM_LEVEL = -2 * DEG;   // photo's beam rests ~2° right-down; level it
const PAN_LEN = 110;           // chain length in design units

// tuning
const BEAM_K = (2 * Math.PI / 2.3) ** 2;   // natural period ≈ 2.3 s
const BEAM_C = 2 * 0.26 * Math.sqrt(BEAM_K);
const SWAY_K = (2 * Math.PI / 1.7) ** 2;
const SWAY_C = 2 * 0.18 * Math.sqrt(SWAY_K);
const PAN_G = (2 * Math.PI / 1.2) ** 2 * PAN_LEN; // pan period ≈ 1.2 s
const PAN_C = 1.05;

const AUTO_AMP = 6.5 * DEG;
const AUTO_PERIOD = 5.4;
const MOUSE_AMP = 15 * DEG;
const IDLE_MS = 900;

const rot = (p, c, a) => {
  const s = Math.sin(a), k = Math.cos(a);
  const dx = p.x - c.x, dy = p.y - c.y;
  return { x: c.x + dx * k - dy * s, y: c.y + dx * s + dy * k };
};
const smooth = (t) => t * t * (3 - 2 * t);

export default function JusticeStatue({ trackRef, paused = false }) {
  const stemRef = useRef(null);
  const beamRef = useRef(null);
  const panLRef = useRef(null);
  const panRRef = useRef(null);

  const [reduce, setReduce] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduce(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (reduce || paused) return;
    const ampScale = 1;

    const s = {
      th: 0, om: 0, al: 0,       // beam
      ph: 0, phv: 0,             // sway
      pans: [
        { tip: L.tipL, psi: 0, v: 0, prev: null, vel: { x: 0, y: 0 }, acc: { x: 0, y: 0 } },
        { tip: L.tipR, psi: 0, v: 0, prev: null, vel: { x: 0, y: 0 }, acc: { x: 0, y: 0 } },
      ],
      mouseN: 0, lastMove: -1e9, w: 0, t: 0,
    };

    const target = trackRef?.current ?? window;
    const onMove = (e) => {
      const el = trackRef?.current;
      const r = el ? el.getBoundingClientRect() : { left: 0, width: window.innerWidth };
      s.mouseN = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
      s.lastMove = performance.now();
    };
    const onLeave = () => { s.lastMove = -1e9; };
    target.addEventListener('pointermove', onMove, { passive: true });
    target.addEventListener('pointerleave', onLeave);

    const tipWorld = (tip) =>
      rot(rot(tip, FULCRUM, s.th + BEAM_LEVEL), HAND, s.ph);

    const step = (dt, now) => {
      s.t += dt;
      // automatic swing: main sine + slow drift so it never looks mechanical
      const auto =
        ampScale * AUTO_AMP *
        (Math.sin((2 * Math.PI * s.t) / AUTO_PERIOD) +
          0.22 * Math.sin((2 * Math.PI * s.t) / 13.7 + 1.3));
      const mouse = ampScale * MOUSE_AMP * s.mouseN;

      const active = now - s.lastMove < IDLE_MS ? 1 : 0;
      const rate = active ? 5 : 0.9;              // fast hand-off in, slow ease out
      s.w += (active - s.w) * (1 - Math.exp(-rate * dt));
      const goal = auto + (mouse - auto) * smooth(Math.min(1, Math.max(0, s.w)));

      // beam: damped spring toward goal → inertia + gentle overshoot
      s.al = BEAM_K * (goal - s.th) - BEAM_C * s.om;
      s.om += s.al * dt;
      s.th += s.om * dt;

      // assembly sway reacts to beam angular acceleration
      const pa = -SWAY_K * s.ph - SWAY_C * s.phv - 0.1 * s.al;
      s.phv += pa * dt;
      s.ph += s.phv * dt;
      s.ph = Math.max(-3 * DEG, Math.min(3 * DEG, s.ph));

      // pans: pendulums driven by tip acceleration
      for (const p of s.pans) {
        const tw = tipWorld(p.tip);
        if (p.prev) {
          const vx = (tw.x - p.prev.x) / dt, vy = (tw.y - p.prev.y) / dt;
          const ax = (vx - p.vel.x) / dt, ay = (vy - p.vel.y) / dt;
          const f = 1 - Math.exp(-dt * 60);         // de-noise finite diff
          p.acc.x += (ax - p.acc.x) * f; p.acc.y += (ay - p.acc.y) * f;
          p.vel.x = vx; p.vel.y = vy;
        }
        p.prev = tw;
        const a =
          -(PAN_G / PAN_LEN) * Math.sin(p.psi) -
          PAN_C * p.v -
          (p.acc.x * Math.cos(p.psi) + p.acc.y * Math.sin(p.psi)) / PAN_LEN;
        p.v += a * dt;
        p.psi += p.v * dt;
        p.world = tw;
      }
    };

    const render = () => {
      const phD = s.ph / DEG;
      stemRef.current.setAttribute('transform', `rotate(${phD} ${HAND.x} ${HAND.y})`);
      beamRef.current.setAttribute(
        'transform',
        `rotate(${phD} ${HAND.x} ${HAND.y}) rotate(${(s.th + BEAM_LEVEL) / DEG} ${FULCRUM.x} ${FULCRUM.y})`
      );
      [panLRef, panRRef].forEach((ref, i) => {
        const p = s.pans[i];
        ref.current.setAttribute(
          'transform',
          `translate(${p.world.x} ${p.world.y}) rotate(${p.psi / DEG}) translate(${-p.tip.x} ${-p.tip.y})`
        );
      });
    };

    let raf, last = performance.now(), acc = 0;
    const H = 1 / 240;
    // warm up so the first frame is already mid-swing, not starting from rest
    for (let i = 0; i < 240 * 3; i++) step(H, -1e9);
    render();

    const loop = (now) => {
      acc += Math.min(0.05, (now - last) / 1000);
      last = now;
      while (acc >= H) { step(H, now); acc -= H; }
      render();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    const onVis = () => { last = performance.now(); };
    document.addEventListener('visibilitychange', onVis);

    return () => {
      cancelAnimationFrame(raf);
      target.removeEventListener('pointermove', onMove);
      target.removeEventListener('pointerleave', onLeave);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [trackRef, reduce, paused]);

  const img = (part, src, ref) => (
    <g ref={ref}>
      <image href={src} x={part.x} y={part.y} width={part.w} height={part.h} />
    </g>
  );

  return (
    <svg
      className="statue"
      viewBox={`0 0 ${L.frame.w} ${L.frame.h}`}
      role="img"
      aria-label="저울을 든 정의의 여신 동상"
    >
      <image href={statueSrc} x="0" y="0" width={L.frame.w} height={L.frame.h} />
      {img(L.stem, stemSrc, stemRef)}
      {img(L.panL, panLSrc, panLRef)}
      {img(L.panR, panRSrc, panRRef)}
      {img(L.beam, beamSrc, beamRef)}
    </svg>
  );
}
