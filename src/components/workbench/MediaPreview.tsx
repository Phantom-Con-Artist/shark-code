import { useState } from 'react';
import { Maximize, Minus, Plus } from 'lucide-react';
import type { OpenFile } from '../../stores/useProjectStore';

export default function MediaPreview({ file }: { file: OpenFile }) {
  const [zoom, setZoom] = useState<number | null>(null);
  const [dimensions, setDimensions] = useState('');
  const [naturalWidth, setNaturalWidth] = useState(0);
  const [error, setError] = useState(false);
  const media = file.media!;
  const name = file.path.split('/').pop()!;
  return <section className="media-preview" aria-label={`Preview of ${name}`}>
    <div className="media-toolbar">
      <span>{media.kind === 'image' ? 'Image' : media.kind === 'video' ? 'Video' : 'Audio'} preview</span>
      <span className="grow" />
      {dimensions && <span>{dimensions}</span>}
      <span>{media.size < 1024 * 1024 ? `${(media.size / 1024).toFixed(1)} KB` : `${(media.size / 1024 / 1024).toFixed(1)} MB`}</span>
      {media.kind === 'image' && <>
        <button className="icon-btn sm" aria-label="Zoom out" disabled={error} onClick={() => setZoom(z => Math.max(10, (z ?? 100) - 25))}><Minus size={14} /></button>
        <button className="btn sm" disabled={error} onClick={() => setZoom(z => z === 100 ? null : 100)}>{zoom === null ? 'Fit' : `${zoom}%`}</button>
        <button className="icon-btn sm" aria-label="Zoom in" disabled={error} onClick={() => setZoom(z => Math.min(800, (z ?? 100) + 25))}><Plus size={14} /></button>
        <button className="icon-btn sm" aria-label="Fit image" disabled={error} onClick={() => setZoom(null)}><Maximize size={14} /></button>
      </>}
    </div>
    <div className={`media-stage ${media.kind}`}>
      {error ? <div className="media-error" role="alert"><strong>Cannot preview this file</strong><p>The file may be damaged, or its format or codec is unavailable in the system player.</p></div> : media.kind === 'image'
        ? <img src={media.url} alt={name} draggable={false} style={zoom === null ? undefined : { maxWidth: 'none', maxHeight: 'none', width: naturalWidth * zoom / 100 }} onLoad={e => {setNaturalWidth(e.currentTarget.naturalWidth); setDimensions(`${e.currentTarget.naturalWidth} × ${e.currentTarget.naturalHeight}`);}} onError={() => setError(true)} />
        : media.kind === 'video' ? <video src={media.url} controls preload="metadata" aria-label={name} onError={() => setError(true)} />
          : <div className="media-audio"><strong>{name}</strong><audio src={media.url} controls preload="metadata" aria-label={name} onError={() => setError(true)} /></div>}
    </div>
  </section>;
}
