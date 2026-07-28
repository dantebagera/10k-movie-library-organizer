import Hls from 'hls.js/dist/hls.light.min.js';
import { AlertTriangle, Loader2, Radio, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { iptvApi } from '../../api/iptv.js';

export default function IPTVPlayer({ playback, compact = false, onClose }) {
  const videoRef = useRef(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !playback?.manifest_url) return undefined;
    let hls;
    let recoveryTimer;
    let startupTimer;
    let playbackStarted = false;
    let networkRecoveryAttempts = 0;
    let mediaRecoveryAttempts = 0;
    const live = playback.kind === 'live';
    const startPlayback = () => {
      if (playbackStarted) return;
      playbackStarted = true;
      window.clearTimeout(startupTimer);
      setState('ready');
      setError('');
      video.play().catch(() => {});
    };
    const tryStartLivePlayback = (force = false) => {
      if (!video.buffered.length) {
        if (force) {
          setState('error');
          setError('The provider is not sending enough data to start this channel.');
        }
        return;
      }
      const index = video.buffered.length - 1;
      const bufferedSeconds = video.buffered.end(index) - Math.max(video.currentTime, video.buffered.start(index));
      if (force || bufferedSeconds >= 12) startPlayback();
    };
    setState('loading');
    setError('');
    if (Hls.isSupported()) {
      hls = new Hls(live ? {
        initialLiveManifestSize: 1,
        liveSyncDuration: 12,
        liveMaxLatencyDuration: 30,
        maxBufferLength: 30,
        backBufferLength: 30,
        lowLatencyMode: false
      } : { maxBufferLength: 60 });
      hls.loadSource(playback.manifest_url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (live) {
          startupTimer = window.setTimeout(() => tryStartLivePlayback(true), 15000);
        } else {
          startPlayback();
        }
      });
      hls.on(Hls.Events.FRAG_LOADED, () => {
        networkRecoveryAttempts = 0;
      });
      hls.on(Hls.Events.FRAG_BUFFERED, () => {
        if (!playbackStarted && live) {
          tryStartLivePlayback();
        } else if (playbackStarted) {
          setState('ready');
          setError('');
          video.play().catch(() => {});
        }
      });
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (!data.fatal) return;
        if (live && data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRecoveryAttempts < 3) {
          networkRecoveryAttempts += 1;
          setState('loading');
          window.clearTimeout(recoveryTimer);
          recoveryTimer = window.setTimeout(() => hls?.startLoad(), networkRecoveryAttempts * 1000);
          return;
        }
        if (live && data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRecoveryAttempts < 2) {
          mediaRecoveryAttempts += 1;
          hls.recoverMediaError();
          return;
        }
        setState('error');
        setError('This provider stream stopped or uses an unsupported codec.');
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = playback.manifest_url;
      video.addEventListener('loadedmetadata', () => setState('ready'), { once: true });
    } else {
      setState('error');
      setError('HLS playback is not supported by this browser.');
    }
    return () => {
      window.clearTimeout(recoveryTimer);
      window.clearTimeout(startupTimer);
      hls?.destroy();
      video.removeAttribute('src');
      video.load();
    };
  }, [playback]);

  useEffect(() => {
    if (!playback || playback.kind === 'live') return undefined;
    const timer = window.setInterval(() => {
      const video = videoRef.current;
      if (!video || !Number.isFinite(video.currentTime)) return;
      iptvApi.history(playback.provider_id, playback.historyKind || playback.kind, playback.historyId || playback.item_id, {
        position_seconds: video.currentTime,
        duration_seconds: Number.isFinite(video.duration) ? video.duration : 0,
        completed: Number.isFinite(video.duration) && video.duration > 0 && video.currentTime / video.duration > 0.92
      }).catch(() => {});
    }, 20000);
    return () => window.clearInterval(timer);
  }, [playback]);

  return (
    <section className={`iptv-player ${compact ? 'iptv-player-compact' : ''}`} aria-label={`Playing ${playback?.title || 'IPTV stream'}`}>
      <div className="iptv-player-stage">
        {playback ? <video ref={videoRef} controls playsInline /> : (
          <div className="iptv-player-empty"><Radio size={38} /><strong>Select something to watch</strong><span>Playback stays inside Cinema Paradiso.</span></div>
        )}
        {playback && state === 'loading' ? <div className="iptv-player-state"><Loader2 className="spin" size={22} /><span>Preparing provider stream...</span></div> : null}
        {state === 'error' ? <div className="iptv-player-state iptv-player-error"><AlertTriangle size={22} /><span>{error}</span></div> : null}
        {playback && onClose ? <button type="button" className="iptv-player-close" onClick={onClose} aria-label="Close IPTV player" title="Close"><X size={18} /></button> : null}
      </div>
      {playback ? <div className="iptv-now-playing"><span>{playback.kind === 'live' ? 'Live now' : 'Now playing'}</span><strong dir="auto">{playback.title}</strong></div> : null}
    </section>
  );
}
