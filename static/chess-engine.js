// chess-engine.js
// A complete, correct, dependency-free JavaScript chess engine.
// Pure ES module. Runs in browsers and Node.js. No imports, no libraries.
//
// Board representation: 0x88 (128-cell array). This makes off-board
// detection trivial via (square & 0x88).
//
// Square index -> (rank, file): index = rank*16 + file, rank 0 = rank "1".
// Algebraic 'e4' maps to file 4, rank 3 -> index 3*16+4 = 52.

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WHITE = 'w';
const BLACK = 'b';

const PAWN = 'p';
const KNIGHT = 'n';
const BISHOP = 'b';
const ROOK = 'r';
const QUEEN = 'q';
const KING = 'k';

const EMPTY = null;

// Castling right bit flags.
const CASTLE_WK = 1; // White king-side
const CASTLE_WQ = 2; // White queen-side
const CASTLE_BK = 4; // Black king-side
const CASTLE_BQ = 8; // Black queen-side

// Move direction offsets in 0x88.
const OFFSETS = {
  n: [-18, -33, -31, -14, 18, 33, 31, 14],
  b: [-17, -15, 17, 15],
  r: [-16, 1, 16, -1],
  q: [-17, -16, -15, 1, 17, 16, 15, -1],
  k: [-17, -16, -15, 1, 17, 16, 15, -1],
};

// Pawn push/capture offsets by color.
const PAWN_PUSH = { w: 16, b: -16 };
const PAWN_CAPTURES = { w: [15, 17], b: [-15, -17] };

// Sliding piece flags for attack detection.
const SLIDERS = { b: true, r: true, q: true };

// ---------------------------------------------------------------------------
// Square helpers (0x88)
// ---------------------------------------------------------------------------

function rankOf(sq) { return sq >> 4; }
function fileOf(sq) { return sq & 0x0f; }
function isOnBoard(sq) { return (sq & 0x88) === 0; }

function algebraic(sq) {
  const f = fileOf(sq);
  const r = rankOf(sq);
  return 'abcdefgh'[f] + (r + 1);
}

function squareFromAlgebraic(s) {
  if (typeof s !== 'string' || s.length !== 2) return -1;
  const f = s.charCodeAt(0) - 97; // 'a'
  const r = s.charCodeAt(1) - 49;  // '1'
  if (f < 0 || f > 7 || r < 0 || r > 7) return -1;
  return r * 16 + f;
}

// ---------------------------------------------------------------------------
// Chess class
// ---------------------------------------------------------------------------

const DEFAULT_FEN =
  'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

class Chess {
  constructor(fen) {
    this._board = new Array(128).fill(EMPTY); // each cell: {type,color} or null
    this._turn = WHITE;
    this._castling = 0;
    this._ep = -1; // en passant target square (0x88 index) or -1
    this._halfmoves = 0;
    this._fullmoves = 1;
    this._kings = { w: -1, b: -1 };
    this._history = []; // list of SAN-ish move records (we store move objects)
    this.load(fen || DEFAULT_FEN);
  }

  // -------------------------------------------------------------------------
  // FEN loading / generation
  // -------------------------------------------------------------------------

  load(fen) {
    const parts = fen.trim().split(/\s+/);
    if (parts.length < 4) {
      throw new Error('Invalid FEN: not enough fields');
    }
    const [placement, active, castling, ep] = parts;
    const halfmoves = parts.length > 4 ? parts[4] : '0';
    const fullmoves = parts.length > 5 ? parts[5] : '1';

    this._board = new Array(128).fill(EMPTY);
    this._kings = { w: -1, b: -1 };

    const ranks = placement.split('/');
    if (ranks.length !== 8) {
      throw new Error('Invalid FEN: board must have 8 ranks');
    }

    // FEN lists rank 8 first. Rank 8 -> internal rank index 7.
    for (let i = 0; i < 8; i++) {
      const row = ranks[i];
      const rankIndex = 7 - i;
      let file = 0;
      for (const ch of row) {
        if (/[1-8]/.test(ch)) {
          file += parseInt(ch, 10);
        } else {
          const color = ch === ch.toUpperCase() ? WHITE : BLACK;
          const type = ch.toLowerCase();
          if (!'pnbrqk'.includes(type)) {
            throw new Error('Invalid FEN: bad piece ' + ch);
          }
          const sq = rankIndex * 16 + file;
          this._board[sq] = { type, color };
          if (type === KING) this._kings[color] = sq;
          file++;
        }
      }
      if (file !== 8) {
        throw new Error('Invalid FEN: rank ' + (8 - i) + ' wrong length');
      }
    }

    this._turn = active === BLACK ? BLACK : WHITE;

    this._castling = 0;
    if (castling.includes('K')) this._castling |= CASTLE_WK;
    if (castling.includes('Q')) this._castling |= CASTLE_WQ;
    if (castling.includes('k')) this._castling |= CASTLE_BK;
    if (castling.includes('q')) this._castling |= CASTLE_BQ;

    this._ep = ep && ep !== '-' ? squareFromAlgebraic(ep) : -1;

    this._halfmoves = parseInt(halfmoves, 10) || 0;
    this._fullmoves = parseInt(fullmoves, 10) || 1;

    this._history = [];
    return this;
  }

  fen() {
    let placement = '';
    for (let r = 7; r >= 0; r--) {
      let empty = 0;
      for (let f = 0; f < 8; f++) {
        const sq = r * 16 + f;
        const piece = this._board[sq];
        if (piece === EMPTY) {
          empty++;
        } else {
          if (empty > 0) { placement += empty; empty = 0; }
          const ch = piece.type;
          placement += piece.color === WHITE ? ch.toUpperCase() : ch;
        }
      }
      if (empty > 0) placement += empty;
      if (r > 0) placement += '/';
    }

    let castling = '';
    if (this._castling & CASTLE_WK) castling += 'K';
    if (this._castling & CASTLE_WQ) castling += 'Q';
    if (this._castling & CASTLE_BK) castling += 'k';
    if (this._castling & CASTLE_BQ) castling += 'q';
    if (castling === '') castling = '-';

    const ep = this._ep >= 0 ? algebraic(this._ep) : '-';

    return [
      placement,
      this._turn,
      castling,
      ep,
      this._halfmoves,
      this._fullmoves,
    ].join(' ');
  }

  // -------------------------------------------------------------------------
  // Basic queries
  // -------------------------------------------------------------------------

  turn() { return this._turn; }

  get(square) {
    const sq = squareFromAlgebraic(square);
    if (sq < 0) return null;
    const p = this._board[sq];
    return p ? { type: p.type, color: p.color } : null;
  }

  board() {
    // 8x8 array, rank 8 first (index 0 = rank 8).
    const out = [];
    for (let r = 7; r >= 0; r--) {
      const row = [];
      for (let f = 0; f < 8; f++) {
        const p = this._board[r * 16 + f];
        row.push(p ? { type: p.type, color: p.color } : null);
      }
      out.push(row);
    }
    return out;
  }

  history() {
    // Return a shallow copy of played move objects.
    return this._history.map((h) => ({
      from: h.move.from,
      to: h.move.to,
      promotion: h.move.promotion,
    }));
  }

  // -------------------------------------------------------------------------
  // Attack detection
  // -------------------------------------------------------------------------

  // Is `square` (0x88 index) attacked by side `color`?
  _isAttacked(square, color) {
    const board = this._board;
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; } // skip off-board columns
      const piece = board[sq];
      if (piece === EMPTY || piece.color !== color) continue;

      const diff = square - sq;
      const type = piece.type;

      if (type === PAWN) {
        // A pawn on `sq` of `color` attacks square diagonally forward.
        for (const off of PAWN_CAPTURES[color]) {
          if (sq + off === square) return true;
        }
        continue;
      }

      if (type === KNIGHT) {
        for (const off of OFFSETS.n) {
          if (sq + off === square) return true;
        }
        continue;
      }

      if (type === KING) {
        for (const off of OFFSETS.k) {
          if (sq + off === square) return true;
        }
        continue;
      }

      // Sliding pieces: bishop, rook, queen.
      const offsets = OFFSETS[type];
      for (const off of offsets) {
        let s = sq + off;
        while (isOnBoard(s)) {
          if (s === square) return true;
          if (board[s] !== EMPTY) break; // blocked
          s += off;
        }
      }
    }
    return false;
  }

  _kingSquare(color) {
    return this._kings[color];
  }

  inCheck() {
    const king = this._kingSquare(this._turn);
    if (king < 0) return false;
    return this._isAttacked(king, this._turn === WHITE ? BLACK : WHITE);
  }

  _isKingAttacked(color) {
    const king = this._kingSquare(color);
    if (king < 0) return false;
    return this._isAttacked(king, color === WHITE ? BLACK : WHITE);
  }

  // -------------------------------------------------------------------------
  // Move generation
  // -------------------------------------------------------------------------

  // Generate pseudo-legal moves as internal move records:
  // { from, to, piece, captured, promotion, flags }
  // flags: 'n' normal, 'b' big pawn (double), 'e' en passant,
  //        'c' capture, 'p' promotion, 'k' king castle, 'q' queen castle
  _generatePseudoMoves(onlyFrom) {
    const moves = [];
    const us = this._turn;
    const them = us === WHITE ? BLACK : WHITE;
    const board = this._board;

    const addPawnMove = (from, to, flags, captured) => {
      const rank = rankOf(to);
      if ((us === WHITE && rank === 7) || (us === BLACK && rank === 0)) {
        for (const promo of [QUEEN, ROOK, BISHOP, KNIGHT]) {
          moves.push({
            from, to, piece: PAWN, captured: captured || null,
            promotion: promo, flags: flags + 'p',
          });
        }
      } else {
        moves.push({
          from, to, piece: PAWN, captured: captured || null,
          promotion: null, flags,
        });
      }
    };

    let start = 0, end = 127;
    if (onlyFrom !== undefined && onlyFrom >= 0) {
      start = onlyFrom;
      end = onlyFrom;
    }

    for (let from = start; from <= end; from++) {
      if (from & 0x88) { from += 7; continue; }
      const piece = board[from];
      if (piece === EMPTY || piece.color !== us) continue;

      const type = piece.type;

      if (type === PAWN) {
        const push = PAWN_PUSH[us];
        const oneStep = from + push;
        // Single push
        if (isOnBoard(oneStep) && board[oneStep] === EMPTY) {
          addPawnMove(from, oneStep, 'n', null);
          // Double push from starting rank
          const startRank = us === WHITE ? 1 : 6;
          if (rankOf(from) === startRank) {
            const twoStep = from + push * 2;
            if (board[twoStep] === EMPTY) {
              moves.push({
                from, to: twoStep, piece: PAWN, captured: null,
                promotion: null, flags: 'b',
              });
            }
          }
        }
        // Captures
        for (const off of PAWN_CAPTURES[us]) {
          const to = from + off;
          if (!isOnBoard(to)) continue;
          const target = board[to];
          if (target !== EMPTY && target.color === them) {
            addPawnMove(from, to, 'c', target.type);
          } else if (to === this._ep) {
            // En passant capture
            moves.push({
              from, to, piece: PAWN, captured: PAWN,
              promotion: null, flags: 'e',
            });
          }
        }
        continue;
      }

      if (type === KNIGHT || type === KING) {
        for (const off of OFFSETS[type]) {
          const to = from + off;
          if (!isOnBoard(to)) continue;
          const target = board[to];
          if (target === EMPTY) {
            moves.push({ from, to, piece: type, captured: null, promotion: null, flags: 'n' });
          } else if (target.color === them) {
            moves.push({ from, to, piece: type, captured: target.type, promotion: null, flags: 'c' });
          }
        }
      } else {
        // Sliding: bishop, rook, queen
        for (const off of OFFSETS[type]) {
          let to = from + off;
          while (isOnBoard(to)) {
            const target = board[to];
            if (target === EMPTY) {
              moves.push({ from, to, piece: type, captured: null, promotion: null, flags: 'n' });
            } else {
              if (target.color === them) {
                moves.push({ from, to, piece: type, captured: target.type, promotion: null, flags: 'c' });
              }
              break;
            }
            to += off;
          }
        }
      }
    }

    // Castling (only when generating all moves, or from the king square).
    const king = this._kingSquare(us);
    if (king >= 0 && (onlyFrom === undefined || onlyFrom < 0 || onlyFrom === king)) {
      this._addCastlingMoves(moves, us, them, king);
    }

    return moves;
  }

  _addCastlingMoves(moves, us, them, king) {
    const board = this._board;
    const rankBase = us === WHITE ? 0 : 112; // rank 1 or rank 8 base index

    // King-side
    const canK = us === WHITE ? (this._castling & CASTLE_WK) : (this._castling & CASTLE_BK);
    if (canK) {
      const f1 = rankBase + 5; // f-file
      const g1 = rankBase + 6; // g-file
      const rookSq = rankBase + 7; // h-file
      const rook = board[rookSq];
      if (
        board[f1] === EMPTY && board[g1] === EMPTY &&
        rook !== EMPTY && rook.type === ROOK && rook.color === us &&
        !this._isAttacked(king, them) &&
        !this._isAttacked(f1, them) &&
        !this._isAttacked(g1, them)
      ) {
        moves.push({ from: king, to: g1, piece: KING, captured: null, promotion: null, flags: 'k' });
      }
    }

    // Queen-side
    const canQ = us === WHITE ? (this._castling & CASTLE_WQ) : (this._castling & CASTLE_BQ);
    if (canQ) {
      const d1 = rankBase + 3;
      const c1 = rankBase + 2;
      const b1 = rankBase + 1;
      const rookSq = rankBase + 0; // a-file
      const rook = board[rookSq];
      if (
        board[d1] === EMPTY && board[c1] === EMPTY && board[b1] === EMPTY &&
        rook !== EMPTY && rook.type === ROOK && rook.color === us &&
        !this._isAttacked(king, them) &&
        !this._isAttacked(d1, them) &&
        !this._isAttacked(c1, them)
      ) {
        moves.push({ from: king, to: c1, piece: KING, captured: null, promotion: null, flags: 'q' });
      }
    }
  }

  // Return legal moves. Filters pseudo-legal moves that leave own king in check.
  _legalMoves(onlyFrom) {
    const pseudo = this._generatePseudoMoves(onlyFrom);
    const legal = [];
    for (const m of pseudo) {
      this._makeMoveInternal(m);
      // After making, turn has flipped; check whether the side that just moved
      // left its own king in check.
      const movedColor = this._turn === WHITE ? BLACK : WHITE;
      if (!this._isKingAttacked(movedColor)) {
        legal.push(m);
      }
      this._undoMoveInternal(m);
    }
    return legal;
  }

  moves({ square } = {}) {
    let onlyFrom = -1;
    if (square !== undefined) {
      onlyFrom = squareFromAlgebraic(square);
      if (onlyFrom < 0) return [];
    }
    const legal = this._legalMoves(onlyFrom >= 0 ? onlyFrom : undefined);
    return legal.map((m) => {
      const out = { from: algebraic(m.from), to: algebraic(m.to) };
      if (m.promotion) out.promotion = m.promotion;
      return out;
    });
  }

  // -------------------------------------------------------------------------
  // Make / undo (internal, operates on internal move records)
  // -------------------------------------------------------------------------

  _makeMoveInternal(m) {
    const board = this._board;
    const us = this._turn;
    const them = us === WHITE ? BLACK : WHITE;

    // Save state for undo.
    m._state = {
      castling: this._castling,
      ep: this._ep,
      halfmoves: this._halfmoves,
      fullmoves: this._fullmoves,
      kingFrom: null,
      capturedSq: -1,
      capturedPiece: null,
    };

    const movingPiece = board[m.from];

    // Handle capture (including en passant).
    if (m.flags.includes('e')) {
      // En passant: captured pawn is behind the target square.
      const capSq = us === WHITE ? m.to - 16 : m.to + 16;
      m._state.capturedSq = capSq;
      m._state.capturedPiece = board[capSq];
      board[capSq] = EMPTY;
    } else if (m.captured) {
      m._state.capturedSq = m.to;
      m._state.capturedPiece = board[m.to];
    }

    // Move the piece.
    board[m.to] = movingPiece;
    board[m.from] = EMPTY;

    // Promotion.
    if (m.promotion) {
      board[m.to] = { type: m.promotion, color: us };
    }

    // King tracking + castling rook move.
    if (movingPiece.type === KING) {
      this._kings[us] = m.to;
      if (m.flags.includes('k')) {
        // King-side: move rook from h to f.
        const rankBase = us === WHITE ? 0 : 112;
        board[rankBase + 5] = board[rankBase + 7];
        board[rankBase + 7] = EMPTY;
      } else if (m.flags.includes('q')) {
        const rankBase = us === WHITE ? 0 : 112;
        board[rankBase + 3] = board[rankBase + 0];
        board[rankBase + 0] = EMPTY;
      }
    }

    // Update castling rights.
    // If a king moves, lose both rights.
    if (movingPiece.type === KING) {
      if (us === WHITE) this._castling &= ~(CASTLE_WK | CASTLE_WQ);
      else this._castling &= ~(CASTLE_BK | CASTLE_BQ);
    }
    // If a rook moves from its home square, lose that right.
    // If a rook is captured on its home square, opponent loses that right.
    this._updateCastlingForSquare(m.from);
    this._updateCastlingForSquare(m.to);

    // En passant square.
    if (m.flags === 'b') {
      this._ep = us === WHITE ? m.from + 16 : m.from - 16;
    } else {
      this._ep = -1;
    }

    // Halfmove clock.
    if (movingPiece.type === PAWN || m.captured) {
      this._halfmoves = 0;
    } else {
      this._halfmoves++;
    }

    // Fullmove number.
    if (us === BLACK) this._fullmoves++;

    // Flip turn.
    this._turn = them;
  }

  _updateCastlingForSquare(sq) {
    // a1=0, h1=7, a8=112, h8=119
    if (sq === 0) this._castling &= ~CASTLE_WQ;
    else if (sq === 7) this._castling &= ~CASTLE_WK;
    else if (sq === 112) this._castling &= ~CASTLE_BQ;
    else if (sq === 119) this._castling &= ~CASTLE_BK;
  }

  _undoMoveInternal(m) {
    const board = this._board;
    // Turn flips back to the mover.
    const them = this._turn;
    const us = them === WHITE ? BLACK : WHITE;
    this._turn = us;

    const st = m._state;
    this._castling = st.castling;
    this._ep = st.ep;
    this._halfmoves = st.halfmoves;
    this._fullmoves = st.fullmoves;

    // Move the piece back.
    const movedPiece = board[m.to];

    // Restore original piece on from (undo promotion).
    if (m.promotion) {
      board[m.from] = { type: PAWN, color: us };
    } else {
      board[m.from] = movedPiece;
    }
    board[m.to] = EMPTY;

    // King tracking.
    if (movedPiece && movedPiece.type === KING) {
      this._kings[us] = m.from;
      // Undo castling rook move.
      if (m.flags.includes('k')) {
        const rankBase = us === WHITE ? 0 : 112;
        board[rankBase + 7] = board[rankBase + 5];
        board[rankBase + 5] = EMPTY;
      } else if (m.flags.includes('q')) {
        const rankBase = us === WHITE ? 0 : 112;
        board[rankBase + 0] = board[rankBase + 3];
        board[rankBase + 3] = EMPTY;
      }
    }

    // Restore captured piece.
    if (st.capturedSq >= 0) {
      board[st.capturedSq] = st.capturedPiece;
    }
  }

  // -------------------------------------------------------------------------
  // Public move
  // -------------------------------------------------------------------------

  move({ from, to, promotion } = {}) {
    const fromSq = squareFromAlgebraic(from);
    const toSq = squareFromAlgebraic(to);
    if (fromSq < 0 || toSq < 0) return null;

    const legal = this._legalMoves(fromSq);
    let chosen = null;
    for (const m of legal) {
      if (m.from === fromSq && m.to === toSq) {
        if (m.promotion) {
          if (promotion && m.promotion === promotion) { chosen = m; break; }
          // Default to queen if promotion not specified.
          if (!promotion && m.promotion === QUEEN) { chosen = m; break; }
        } else {
          chosen = m;
          break;
        }
      }
    }

    if (!chosen) return null;

    this._makeMoveInternal(chosen);
    this._history.push({
      move: {
        from: algebraic(chosen.from),
        to: algebraic(chosen.to),
        promotion: chosen.promotion || undefined,
      },
      internal: chosen,
    });

    return {
      from: algebraic(chosen.from),
      to: algebraic(chosen.to),
      promotion: chosen.promotion || undefined,
    };
  }

  undo() {
    const last = this._history.pop();
    if (!last) return null;
    this._undoMoveInternal(last.internal);
    return last.move;
  }

  // -------------------------------------------------------------------------
  // Game state
  // -------------------------------------------------------------------------

  isCheckmate() {
    return this.inCheck() && this._legalMoves().length === 0;
  }

  isStalemate() {
    return !this.inCheck() && this._legalMoves().length === 0;
  }

  _insufficientMaterial() {
    // Count pieces.
    const pieces = { w: [], b: [] };
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = this._board[sq];
      if (p) pieces[p.color].push({ type: p.type, sq });
    }
    const all = pieces.w.concat(pieces.b);

    // Any pawn, rook, or queen => sufficient.
    for (const p of all) {
      if (p.type === PAWN || p.type === ROOK || p.type === QUEEN) return false;
    }

    const total = all.length;
    // K vs K
    if (total === 2) return true;
    // K+minor vs K
    if (total === 3) {
      // The extra piece is a bishop or knight (pawns/rooks/queens excluded above).
      return true;
    }
    // K+B vs K+B with bishops on same color square.
    if (total === 4) {
      const bishops = all.filter((p) => p.type === BISHOP);
      if (bishops.length === 2 && pieces.w.length === 2 && pieces.b.length === 2) {
        // One bishop each side. Check same-color squares.
        const sqColor = (sq) => (rankOf(sq) + fileOf(sq)) % 2;
        if (sqColor(bishops[0].sq) === sqColor(bishops[1].sq)) return true;
      }
    }
    return false;
  }

  isDraw() {
    if (this._halfmoves >= 100) return true; // 50-move rule
    if (this._insufficientMaterial()) return true;
    if (this.isStalemate()) return true;
    return false;
  }

  isGameOver() {
    return this.isCheckmate() || this.isStalemate() || this.isDraw();
  }

  result() {
    if (this.isCheckmate()) {
      // The side to move is checkmated and loses.
      return this._turn === WHITE ? '0-1' : '1-0';
    }
    if (this.isStalemate() || this.isDraw()) {
      return '1/2-1/2';
    }
    return null;
  }

  // -------------------------------------------------------------------------
  // Perft (node counting for correctness verification)
  // -------------------------------------------------------------------------

  perft(depth) {
    if (depth === 0) return 1;
    const moves = this._generatePseudoMoves();
    let nodes = 0;
    const us = this._turn;
    for (const m of moves) {
      this._makeMoveInternal(m);
      if (!this._isKingAttacked(us)) {
        nodes += this.perft(depth - 1);
      }
      this._undoMoveInternal(m);
    }
    return nodes;
  }
}

// Standalone perft from the start position (or a given FEN).
function perft(depth, fen) {
  const game = new Chess(fen || DEFAULT_FEN);
  return game.perft(depth);
}

Chess.perft = perft;

export { Chess, perft };
export default Chess;

// ---------------------------------------------------------------------------
// Self-test (Node only, when executed directly)
// ---------------------------------------------------------------------------

if (
  typeof process !== 'undefined' &&
  process.argv &&
  process.argv[1] &&
  process.argv[1].endsWith('chess-engine.js')
) {
  const expected = { 1: 20, 2: 400, 3: 8902, 4: 197281 };
  let allPass = true;
  const game = new Chess();
  for (const depth of [1, 2, 3, 4]) {
    const start = Date.now();
    const nodes = game.perft(depth);
    const ms = Date.now() - start;
    const ok = nodes === expected[depth];
    if (!ok) allPass = false;
    console.log(
      `${ok ? 'PASS' : 'FAIL'} perft(${depth}) = ${nodes} ` +
      `(expected ${expected[depth]}) [${ms}ms]`
    );
  }
  if (allPass) {
    console.log('All perft tests PASSED.');
    process.exit(0);
  } else {
    console.error('Some perft tests FAILED.');
    process.exit(1);
  }
}
