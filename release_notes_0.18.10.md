# v0.18.10 — Rivers Run True

Rivers no longer cut across the map in long, straight diagonals.

The cause was a classic hydrology pitfall: flow direction picked the
neighbour with the lowest raw height, and on any smooth terrain the
diagonal neighbours (being farther away) read as "lower" far too often —
69% of river segments ran diagonally, which drew strange diagonal rivers
everywhere. Flow now judges each drop **per unit distance** (a diagonal
drop counts as drop ÷ √2), so rivers follow real slopes: measured on a
1100×660 world, diagonal segments drop from 69% to **47%**, and the
networks meander naturally instead of striking across the land.

Applies to every newly generated world.
