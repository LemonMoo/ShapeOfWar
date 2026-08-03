# v0.11.1 — Marching Orders

A patch on the real-time build: one change to how war works, and two things
that were making a running world unpleasant to watch.

## An attack is a march

Ordering an attack used to fight it on the spot, wherever your commander
happened to be standing. That is what an order means when a turn is the only
thing that makes "later" real — and with a clock running it was simply wrong.

Now the order starts a march. The column crosses the ground, the days pass,
and the battle is fought when it arrives. On a real save an enemy province 130
cells away took **22 days** to reach.

The good consequence is the one that was not designed: **an attack can now be
seen coming, and met.**

## The build menu stays put

It was tearing down and rebuilding every widget it had, every day. A menu that
reconstructs itself under the pointer cannot be read, let alone used.

It now redraws only when something it actually shows has changed — a building
finished, a project started, something becoming affordable. Countdowns tick in
place, your scroll position survives, and pressing a button still answers
immediately.

## A smoother world

Two fixes, both measured:

- The road network's cache checked whether it was stale by summing over
  fourteen hundred regions — **on every single call**, once per cell of every
  convoy's route. That was 13.7 million operations per 150 frames to confirm
  nothing had changed.
- The world then did a day's work flat out and idled until the next one was
  due: half a second of everything, two seconds of nothing, with every dropped
  frame in the first half second. Each frame now takes the share of the day it
  is actually worth, measured against what a day really costs on your world.

Mean frame time **17.7 ms → 5.1 ms**, median **1.9 ms**.

## Days, not turns

Marches, construction, claims and shipyards are all quoted in days now. The
world runs on a clock; nothing should still be counted in turns nobody takes.
