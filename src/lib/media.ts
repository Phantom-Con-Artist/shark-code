export type MediaKind = 'image' | 'video' | 'audio';
export function mediaKind(path: string): MediaKind | null {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'bmp', 'ico'].includes(ext)) return 'image';
  if (['mp4', 'webm', 'ogv', 'mov', 'm4v', 'mkv'].includes(ext)) return 'video';
  if (['mp3', 'wav', 'ogg', 'oga', 'flac', 'm4a', 'aac', 'opus'].includes(ext)) return 'audio';
  return null;
}
export function releaseMedia(url?: string) { if (url?.startsWith('blob:')) URL.revokeObjectURL(url); }
