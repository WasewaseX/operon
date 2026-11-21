//! lexer/scan.rs, the shared cursor state and the dispatch classes that
//! claim one whitespace/mark/number/identifier token per call. Strings and
//! operators live in the `strings` and `ops` submodules; `lex` in the root
//! owns the driver loop.

use crate::ast::Note;

use super::{lex_note, Tok};

pub(super) struct Lexer {
    pub(super) chars: Vec<char>,
    pub(super) i: usize,
    pub(super) n: usize,
    pub(super) line: usize,
    pub(super) toks: Vec<(Tok, usize)>,
    pub(super) notes: Vec<Note>,
    pub(super) docs: Vec<(usize, String)>,
}

impl Lexer {
    pub(super) fn new(src: &str) -> Lexer {
        Lexer {
            chars: src.chars().collect(),
            i: 0,
            n: src.chars().count(),
            line: 1,
            toks: Vec::new(),
            notes: Vec::new(),
            docs: Vec::new(),
        }
    }

    pub(super) fn push(&mut self, t: Tok) {
        self.toks.push((t, self.line));
    }

    pub(super) fn note_r4(&mut self, msg: impl Into<String>) {
        lex_note(
            &mut self.notes,
            Note {
                line: self.line,
                rung: 4,
                message: msg.into(),
            },
        );
    }

    /// Whitespace (not newline) and newline tokens. Newlines collapse: a
    /// repeated `\n` advances the line without emitting a second Newline.
    /// Returns true when the cursor moved.
    pub(super) fn skip_blank(&mut self) -> bool {
        let c = self.chars[self.i];
        if c == ' ' || c == '\t' || c == '\r' {
            self.i += 1;
            return true;
        }
        if c == '\n' {
            if let Some((Tok::Newline, _)) = self.toks.last() {
                self.i += 1;
                self.line += 1;
                return true;
            }
            self.push(Tok::Newline);
            self.i += 1;
            self.line += 1;
            return true;
        }
        false
    }

    /// Comments. W074: `##` opens a DOC comment, captured as metadata
    /// (Lexed docs), never emitted as a token. The marker must be exactly
    /// two `#` (a `###` line is a doc whose text starts with `#`, same
    /// convention as markdown headings inside doc text). A plain `#` line
    /// comment is skipped to end of line. Returns true when the cursor sat
    /// on either form.
    pub(super) fn scan_comment(&mut self) -> bool {
        if self.chars[self.i] != '#' {
            return false;
        }
        if self.i + 1 < self.n && self.chars[self.i + 1] == '#' {
            let mut j = self.i + 2;
            let mut text = String::new();
            if j < self.n && self.chars[j] == ' ' {
                j += 1; // one leading space after the marker is stripped
            }
            while j < self.n && self.chars[j] != '\n' {
                text.push(self.chars[j]);
                j += 1;
            }
            self.docs.push((self.line, text));
            self.i = j;
            return true;
        }
        while self.i < self.n && self.chars[self.i] != '\n' {
            self.i += 1;
        }
        true
    }

    /// `@word` marks; a bare `@` with no word is a rung-4 note.
    pub(super) fn scan_mark(&mut self) -> bool {
        if self.chars[self.i] != '@' {
            return false;
        }
        let start = self.i + 1;
        let mut j = start;
        while j < self.n && (self.chars[j].is_ascii_alphanumeric() || self.chars[j] == '_') {
            j += 1;
        }
        let word: String = self.chars[start..j].iter().collect();
        if word.is_empty() {
            self.note_r4("stray '@' skipped");
        } else {
            self.push(Tok::Mark(word));
        }
        self.i = j;
        true
    }

    /// Numbers: radix-prefixed integers (W031), decimal ints/floats with
    /// `_` separators and an exponent part.
    pub(super) fn scan_number(&mut self) -> bool {
        if !self.chars[self.i].is_ascii_digit() {
            return false;
        }
        if self.scan_radix_int() {
            return true;
        }
        self.scan_decimal();
        true
    }

    /// W031: radix prefixes, 0x hex, 0b binary, 0o octal (case-insensitive
    /// prefix), with `_` digit separators. A prefix with no valid digit
    /// after it falls through to decimal lexing (`0x` = 0 then ident `x`).
    fn scan_radix_int(&mut self) -> bool {
        let c = self.chars[self.i];
        if c != '0' || self.i + 1 >= self.n {
            return false;
        }
        let radix = match self.chars[self.i + 1] {
            'x' | 'X' => 16,
            'b' | 'B' => 2,
            'o' | 'O' => 8,
            _ => return false,
        };
        let valid = |ch: char| match radix {
            16 => ch.is_ascii_hexdigit(),
            2 => ch == '0' || ch == '1',
            _ => ('0'..='7').contains(&ch),
        };
        let head = self.chars[self.i + 2];
        if self.i + 2 >= self.n || !(valid(head) || head == '_') {
            return false;
        }
        let mut j = self.i + 2;
        while j < self.n && (valid(self.chars[j]) || self.chars[j] == '_') {
            j += 1;
        }
        let raw: String = self.chars[self.i..j].iter().collect();
        let digits: String = self.chars[self.i + 2..j]
            .iter()
            .filter(|&&ch| ch != '_')
            .collect();
        self.i = j;
        match i64::from_str_radix(&digits, radix) {
            Ok(v) => self.push(Tok::Int(v)),
            Err(_) => {
                // #115 (Z-115-LEXZERO): the note says "treated as 0" and the
                // ORACLE pushes INT 0 — the token MUST exist, otherwise the
                // parser's Null substitution eats the statement (and its line
                // break), diverging from the oracle and merging the next
                // statement into this one
                self.note_r4(format!("integer '{}' out of range treated as 0", raw));
                self.push(Tok::Int(0));
            }
        }
        true
    }

    /// Decimal literal: digit/`.`/`_` run (a dot only counts when followed
    /// by a digit, so `1.map` stays int + member), optional exponent, then
    /// the W031 separator strip before parsing.
    fn scan_decimal(&mut self) {
        let start = self.i;
        let mut is_float = false;
        while self.i < self.n
            && (self.chars[self.i].is_ascii_digit()
                || self.chars[self.i] == '.'
                || self.chars[self.i] == '_')
        {
            if self.chars[self.i] == '.'
                && (self.i + 1 >= self.n || !self.chars[self.i + 1].is_ascii_digit())
            {
                break;
            }
            if self.chars[self.i] == '.' {
                is_float = true;
            }
            self.i += 1;
        }
        if self.scan_exponent() {
            is_float = true;
        }
        let text: String = self.chars[start..self.i].iter().collect();
        // W031: `_` separators are stripped before parsing (raw text is
        // preserved in the out-of-range note for diagnosis)
        let cleaned: String = text.chars().filter(|&ch| ch != '_').collect();
        if is_float {
            match cleaned.parse::<f64>() {
                Ok(f) => self.push(Tok::Float(f)),
                Err(_) => {
                    // #115 (Z-115-LEXZERO): oracle parity — the malformed
                    // number is INT 0, not Float 0.0, with the note
                    // (bootstrap/oracle.py pushes ("INT", 0) here)
                    self.note_r4(format!("malformed number '{}' treated as 0", text));
                    self.push(Tok::Int(0));
                }
            }
        } else {
            match cleaned.parse::<i64>() {
                Ok(v) => self.push(Tok::Int(v)),
                Err(_) => {
                    // #115 (Z-115-LEXZERO): the note says "treated as 0" and
                    // the ORACLE pushes INT 0 — the token MUST exist (see the
                    // radix arm above)
                    self.note_r4(format!("integer '{}' out of range treated as 0", text));
                    self.push(Tok::Int(0));
                }
            }
        }
    }

    /// `e`/`E` optional-sign exponent tail; true when one was consumed.
    fn scan_exponent(&mut self) -> bool {
        if self.i >= self.n || !(self.chars[self.i] == 'e' || self.chars[self.i] == 'E') {
            return false;
        }
        let mut j = self.i + 1;
        if j < self.n && (self.chars[j] == '+' || self.chars[j] == '-') {
            j += 1;
        }
        if j >= self.n || !self.chars[j].is_ascii_digit() {
            return false;
        }
        self.i = j;
        while self.i < self.n && self.chars[self.i].is_ascii_digit() {
            self.i += 1;
        }
        true
    }

    /// Identifiers/keywords; every name is interned into the in-process
    /// symbol table (src/ffi.rs, Rust-owned since sec-r2/A15), the canonical
    /// record of all symbols in all files: memory() stats, REPL :symbols,
    /// and the future LSP goto-definition all read from it.
    pub(super) fn scan_ident(&mut self) -> bool {
        let c = self.chars[self.i];
        if !(c.is_ascii_alphabetic() || c == '_') {
            return false;
        }
        let start = self.i;
        while self.i < self.n && (self.chars[self.i].is_ascii_alphanumeric() || self.chars[self.i] == '_') {
            self.i += 1;
        }
        let word: String = self.chars[start..self.i].iter().collect();
        crate::ffi::intern(&word);
        self.push(Tok::Ident(word));
        true
    }
}
