#!/usr/bin/env bun
// A stand-in for the baton server's watch API, for running the watch app in the simulator without
// a Spotify account. It keeps a small in-memory player and logs one line per request (the Bearer
// key itself is never printed).
//
//   WATCH_KEY=<key> PORT=8099 SCENARIO=playing bun watch/tools/stub-server.ts
//
// SCENARIO: playing (default), paused, asleep, auth, notrack, rejected. A running stub switches
// scenario, with a fresh player, on GET /__stub/scenario?name=<scenario>.
const port = Number(process.env.PORT ?? 8099)
const key = process.env.WATCH_KEY ?? 'stub-key'
let scenario = process.env.SCENARIO ?? 'playing'

const tracks = [
  { title: 'Midnight City', artist: 'M83', duration: 243000 },
  { title: 'A Very Long Track Title That Needs To Wrap Across Lines', artist: 'An Artist With A Long Name', duration: 312000 },
  { title: 'Intro', artist: 'The xx', duration: 127000 },
]
const playlists = [
  { id: 'pl1', name: 'My Shazam' },
  { id: 'pl2', name: 'Road trip' },
  { id: 'pl3', name: 'Focus' },
]

let index = 0
let playing = false
let progress = 0
let anchor = 0
const liked = new Set<number>()
const inPlaylist = new Set<number>()
const inPlaying = new Set<number>()

function reset(name: string) {
  scenario = name
  index = 0
  playing = name === 'playing'
  progress = 61000
  anchor = Date.now()
  liked.clear()
  inPlaylist.clear()
  inPlaying.clear()
}
reset(scenario)

// A playing track moves on to the next one when it ends.
function position() {
  if (!playing) return progress
  let at = progress + (Date.now() - anchor)
  while (at >= tracks[index].duration) {
    at -= tracks[index].duration
    index = (index + 1) % tracks.length
  }
  setPosition(at)
  return at
}

function setPosition(ms: number) {
  progress = ms
  anchor = Date.now()
}

function state() {
  const t = tracks[index]
  return {
    is_playing: playing,
    track_id: `track${index}`,
    title: t.title,
    artist: t.artist,
    progress_ms: position(),
    duration_ms: t.duration,
    liked: liked.has(index),
    in_playlist: inPlaylist.has(index),
    playlist_name: 'My Shazam',
    playing_playlist_name: 'Cycling',
    in_playing_playlist: inPlaying.has(index),
    device_name: 'Stub phone',
    server_time_ms: Date.now(),
  }
}

const reply = (result: 'ok' | 'already' | 'error', extra: Record<string, unknown> = {}) =>
  Response.json({ result, error: null, message: null, state: null, ...extra })

const fail = (error: string, message: string) => reply('error', { error, message })

function handle(method: string, path: string, mode: string | null, track: string | null) {
  if (track !== null && track !== `track${index}`) return reply('error', { error: 'track_changed', message: 'The song changed', state: state() })
  if (scenario === 'asleep') return fail('no_device', 'No active device')
  if (scenario === 'auth') return fail('spotify_auth', 'Spotify login expired')
  if (scenario === 'notrack') return fail('no_track', 'Nothing playing')
  const set = (_unused: boolean, s: Set<number>, add: boolean) => {
    const was = s.has(index) === add
    if (!was) add ? s.add(index) : s.delete(index)
    return reply(was ? 'already' : 'ok', { state: state() })
  }
  switch (`${method} ${path}`) {
    case 'GET /api/watch/state':
      return reply('ok', { state: state() })
    case 'POST /api/watch/play-pause':
      setPosition(position())
      playing = !playing
      return reply('ok', { state: state() })
    case 'POST /api/watch/next':
      index = (index + 1) % tracks.length
      setPosition(0)
      return reply('ok', { state: state() })
    case 'POST /api/watch/restart':
      setPosition(0)
      return reply('ok', { state: state() })
    case 'POST /api/watch/previous-track':
      index = (index + tracks.length - 1) % tracks.length
      setPosition(0)
      return reply('ok', { state: state() })
    case 'POST /api/watch/like':
      return set(true, liked, true)
    case 'POST /api/watch/unlike':
      return set(true, liked, false)
    case 'POST /api/watch/playlist/add':
      return set(true, inPlaylist, true)
    case 'POST /api/watch/playlist/remove':
      return set(true, inPlaylist, false)
    case 'POST /api/watch/playing-playlist/add':
      return set(true, inPlaying, true)
    case 'POST /api/watch/playing-playlist/remove':
      return set(true, inPlaying, false)
    case 'GET /api/watch/playlists':
      return reply('ok', { playlists })
  }
  const play = path.match(/^\/api\/watch\/playlists\/([^/]+)\/play$/)
  if (method === 'POST' && play) {
    const smart = mode === 'smart'
    playing = true
    return reply('ok', { message: smart ? 'Smart shuffle unavailable, shuffling' : null, state: state() })
  }
  return fail('bad_request', 'Unknown endpoint')
}

Bun.serve({
  port,
  hostname: '0.0.0.0',
  fetch(req) {
    const url = new URL(req.url)
    if (url.pathname === '/__stub/scenario') {
      reset(url.searchParams.get('name') ?? 'playing')
      return new Response(`scenario ${scenario}\n`)
    }
    const auth = req.headers.get('authorization')
    const authOk = auth === `Bearer ${key}`
    console.log(`${new Date().toISOString()} ${req.method} ${url.pathname}${url.search} auth=${authOk ? 'ok' : 'bad'} type=${req.headers.get('content-type') ?? '-'}`)
    if (!authOk || scenario === 'rejected') return new Response('{"detail":"invalid key"}', { status: 401, headers: { 'content-type': 'application/json' } })
    return handle(req.method, url.pathname, url.searchParams.get('mode'), url.searchParams.get('track'))
  },
})
console.log(`stub listening on :${port}, scenario ${scenario}`)
