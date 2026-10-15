export const CHAT_DETACH_EDGE_PX = 48;

export function isChatDetachPoint(
  x: number,
  y: number,
  width = window.innerWidth,
  height = window.innerHeight,
): boolean {
  return x < 0 || y < 0 || x >= width || y >= height || x >= width - CHAT_DETACH_EDGE_PX;
}
