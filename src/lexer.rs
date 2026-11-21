//! lexer.rs, tokenizer. Produces raw tokens; keyword recognition happens in
//! the parser so the wobble ladder (rungs 2/3) can repair at the positions
//! where a keyword is actually required.
//!
//! The scan loop is a thin driver: per-class scanners live in the `scan`,
//! `strings` and `ops` submodules and share one `Lexer` cursor state.

mod ops;
mod scan;
mod strings;

use crate::ast::Note;
use scan::Lexer;

#[derive(Debug, Clone, PartialEq)]
pub enum Tok {
    Ident(String),
    Int(i64),
    Float(f64),
    Str(String),    // no interpolation present
    Interp(String), // raw content, contains {..} parts
    Bytes(Vec<u8>), // W029: b"..." byte-string literal (no interpolation)
    Mark(String),   // @word
    Newline,
    LBrace,
    RBrace,
    LParen,
    RParen,
    LBrack,
    RBrack,
    Comma,
    Colon,
    Arrow,    // ->
    FatArrow, // =>
    Plus,
    Minus,
    Star,
    Slash,
    DSlash,
    Percent,
    PlusEq,
    MinusEq,
    StarEq,
    SlashEq,
    DSlashEq,
    PercentEq,
    StarStar,
    Amp,
    Pipe,
    Caret,
    Tilde,
    Shl,
    Shr,
    Question,
    QuestionDot,      // ?., optional chaining (L1a)
    QuestionQuestion, // ??, null coalescing (L1a)
    QuestionBang,     // ?!, Option/Result propagation (W06, D-014)
    Eq,
    EqEq,
    Neq,
    Lt,
    Le,
    Gt,
    Ge,
    AmpAmp,
    PipePipe,
    Bang,
    Dot,
    Semi,
    Eof,
}

impl Tok {
    /// dx-r1: programmer-facing token name for diagnostics. Rust's Debug
    /// output leaked internal enum shapes like `Str("boom")` into user
    /// messages; describe() speaks in source terms instead.
    pub fn describe(&self) -> String {
        match self {
            Tok::Ident(w) => w.clone(),
            Tok::Int(i) => i.to_string(),
            Tok::Float(f) => format!("{}", f),
            Tok::Str(s) | Tok::Interp(s) => format!("\"{}\"", s),
            Tok::Bytes(_) => "b\"...\"".to_string(),
            Tok::Mark(m) => format!("@{}", m),
            Tok::Newline => "newline".to_string(),
            Tok::LBrace => "'{'".to_string(),
            Tok::RBrace => "'}'".to_string(),
            Tok::LParen => "'('".to_string(),
            Tok::RParen => "')'".to_string(),
            Tok::LBrack => "'['".to_string(),
            Tok::RBrack => "']'".to_string(),
            Tok::Comma => "','".to_string(),
            Tok::Colon => "':'".to_string(),
            Tok::Arrow => "'->'".to_string(),
            Tok::FatArrow => "'=>'".to_string(),
            Tok::Plus => "'+'".to_string(),
            Tok::Minus => "'-'".to_string(),
            Tok::Star => "'*'".to_string(),
            Tok::Slash => "'/'".to_string(),
            Tok::DSlash => "'//'".to_string(),
            Tok::Percent => "'%'".to_string(),
            Tok::PlusEq => "'+='".to_string(),
            Tok::MinusEq => "'-='".to_string(),
            Tok::StarEq => "'*='".to_string(),
            Tok::SlashEq => "'/='".to_string(),
            Tok::DSlashEq => "'//='".to_string(),
            Tok::PercentEq => "'%='".to_string(),
            Tok::StarStar => "'**'".to_string(),
            Tok::Amp => "'&'".to_string(),
            Tok::Pipe => "'|'".to_string(),
            Tok::Caret => "'^'".to_string(),
            Tok::Tilde => "'~'".to_string(),
            Tok::Shl => "'<<'".to_string(),
            Tok::Shr => "'>>'".to_string(),
            Tok::Question => "'?'".to_string(),
            Tok::QuestionDot => "'?.'".to_string(),
            Tok::QuestionQuestion => "'??'".to_string(),
            Tok::QuestionBang => "'?!'".to_string(),
            Tok::Eq => "'='".to_string(),
            Tok::EqEq => "'=='".to_string(),
            Tok::Neq => "'!='".to_string(),
            Tok::Lt => "'<'".to_string(),
            Tok::Le => "'<='".to_string(),
            Tok::Gt => "'>'".to_string(),
            Tok::Ge => "'>='".to_string(),
            Tok::AmpAmp => "'&&'".to_string(),
            Tok::PipePipe => "'||'".to_string(),
            Tok::Bang => "'!'".to_string(),
            Tok::Dot => "'.'".to_string(),
            Tok::Semi => "';'".to_string(),
            Tok::Eof => "end of input".to_string(),
        }
    }
}

pub struct Lexed {
    pub toks: Vec<(Tok, usize)>, // token + line
    pub notes: Vec<Note>,
    /// W074: `##` doc-comment lines, in source order, (line, text after the
    /// `##` marker with one leading space stripped). Pure metadata: docs are
    /// NOT tokens, so the token stream (and every existing consumer of it,
    /// wobble scoring, repair rungs, the differential oracle) is untouched.
    /// Plain `#` comments stay invisible exactly as before.
    pub docs: Vec<(usize, String)>,
}

// sec-r4 (F-3): parse-time note cap, mirrors the Parser/Interp 10k contract.
// A 3 MB file of repairable errors used to grow 1.5 M notes (646 MB RSS).
fn lex_note(buf: &mut Vec<Note>, n: Note) {
    const LEX_NOTE_CAP: usize = 10_000;
    if buf.len() >= LEX_NOTE_CAP {
        if buf.len() == LEX_NOTE_CAP {
            buf.push(Note {
                line: n.line,
                rung: 4,
                message: "lex note cap (10000) reached - further notes suppressed".into(),
            });
        }
        return;
    }
    buf.push(n);
}

/// The whole source -> tokens + notes + docs. One cursor, one dispatch
/// loop; each scanner class claims the cursor or hands it to the next.
pub fn lex(src: &str) -> Lexed {
    let mut lx = Lexer::new(src);
    while lx.i < lx.n {
        if lx.skip_blank() {
            continue;
        }
        if lx.scan_comment() {
            continue;
        }
        if lx.scan_stringlike() {
            continue;
        }
        if lx.scan_mark() {
            continue;
        }
        if lx.scan_number() {
            continue;
        }
        if lx.scan_ident() {
            continue;
        }
        lx.scan_operator();
    }
    lx.push(Tok::Eof);
    Lexed {
        toks: lx.toks,
        notes: lx.notes,
        docs: lx.docs,
    }
}
