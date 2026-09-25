"use client";

import { motion } from "motion/react";

import { cn } from "@/lib/utils";
import { EASE } from "@/lib/motion";

type Cube = [x: number, y: number, fill: string];

/* Pixel-ring monogram: eight 3-unit cubes forming an "O", filled with the
   warm ramp the Mistral logotype uses, clockwise from the top-left cube. */
const CUBES: Cube[] = [
  [3, 0, "#ffaf01"],
  [6, 0, "#ff8204"],
  [9, 3, "#fa500f"],
  [9, 6, "#e61300"],
  [6, 9, "#c4001d"],
  [3, 9, "#e61300"],
  [0, 6, "#fa500f"],
  [0, 3, "#ff8204"],
];

export function PixelMark({
  className,
  assemble = true,
}: {
  className?: string;
  assemble?: boolean;
}) {
  return (
    <motion.svg
      viewBox="0 0 12 12"
      aria-hidden="true"
      className={cn("block shrink-0", className)}
      initial={assemble ? { opacity: 0, scale: 0.8 } : false}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.45, ease: EASE }}
    >
      {CUBES.map(([x, y, fill], i) => (
        <motion.rect
          key={`${x}-${y}`}
          x={x}
          y={y}
          width={3}
          height={3}
          fill={fill}
          initial={assemble ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, delay: i * 0.045, ease: "easeOut" }}
        />
      ))}
    </motion.svg>
  );
}

/* Streaming indicator: three pixel cubes walking down the warm ramp,
   blinking in sequence with the same block grammar as the monogram. */
const CURSOR_FILLS = ["#ffaf01", "#ff8204", "#fa500f"];

export function PixelCursor({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Generating response"
      className={cn("inline-flex items-center gap-[3px]", className)}
    >
      {CURSOR_FILLS.map((fill, i) => (
        <span
          key={i}
          className="pixel-cube block h-[6px] w-[6px]"
          style={{ background: fill, animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}
