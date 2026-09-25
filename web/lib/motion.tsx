"use client";

import type { ReactNode } from "react";
import { MotionConfig, type Transition, type Variants } from "motion/react";

/* Shared motion language: confident ease-out arrivals, quick routine
   changes, springs for touch feedback. reducedMotion="user" keeps
   opacity and color while dropping spatial movement for anyone who
   asks the system for less. */

export const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

export const transition: Transition = { duration: 0.25, ease: EASE };

export const spring: Transition = { type: "spring", stiffness: 500, damping: 30 };

/* Rise-into-place for entering content. */
export const riseIn: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition },
};

/* Parent that staggers direct children into place; delays stay capped. */
export const stagger: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
};

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={transition}>
      {children}
    </MotionConfig>
  );
}
