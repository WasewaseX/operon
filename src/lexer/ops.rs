//! lexer/ops.rs, the operator scanner: single-character tokens inline,
//! two-character lookahead operators split per family so each scan stays
//! inside the structural budgets.

use super::scan::Lexer;
use super::Tok;


impl Lexer {
    /// The operator fallback of the lex driver: single-char tokens are
    /// emitted directly, lookahead operators go to scan_multi_op.
    pub(super) fn scan_operator(&mut self) {
        let c = self.chars[self.i];
        match c {
            '{' => {
                self.push(Tok::LBrace);
                self.i += 1;
            }
            '}' => {
                self.push(Tok::RBrace);
                self.i += 1;
            }
            '(' => {
                self.push(Tok::LParen);
                self.i += 1;
            }
            ')' => {
                self.push(Tok::RParen);
                self.i += 1;
            }
            '[' => {
                self.push(Tok::LBrack);
                self.i += 1;
            }
            ']' => {
                self.push(Tok::RBrack);
                self.i += 1;
            }
            ',' => {
                self.push(Tok::Comma);
                self.i += 1;
            }
            ':' => {
                self.push(Tok::Colon);
                self.i += 1;
            }
            '.' => {
                self.push(Tok::Dot);
                self.i += 1;
            }
            ';' => {
                self.push(Tok::Semi);
                self.i += 1;
            }
            '^' => {
                self.push(Tok::Caret);
                self.i += 1;
            }
            '~' => {
                self.push(Tok::Tilde);
                self.i += 1;
            }
            '+' | '*' | '/' | '%' | '-' | '=' | '!' | '<' | '>' | '&' | '|' | '?' => {
                self.scan_multi_op(c)
            }
            other => {
                self.note_r4(format!("unexpected character '{}' skipped", other));
                self.i += 1;
            }
        }
    }

    /// Two-character operators. Every arm matches the longest form first.
    fn scan_multi_op(&mut self, c: char) {
        match c {
            '+' => self.op_with_eq(Tok::PlusEq, Tok::Plus),
            '-' => {
                if self.next_is('>') {
                    self.push(Tok::Arrow);
                    self.i += 2;
                } else {
                    self.op_with_eq(Tok::MinusEq, Tok::Minus);
                }
            }
            '*' => {
                if self.next_is('*') {
                    self.push(Tok::StarStar);
                    self.i += 2;
                } else {
                    self.op_with_eq(Tok::StarEq, Tok::Star);
                }
            }
            '/' => {
                if self.next_is('/') {
                    if self.next_is2('=') {
                        self.push(Tok::DSlashEq);
                        self.i += 3;
                    } else {
                        self.push(Tok::DSlash);
                        self.i += 2;
                    }
                } else {
                    self.op_with_eq(Tok::SlashEq, Tok::Slash);
                }
            }
            '%' => self.op_with_eq(Tok::PercentEq, Tok::Percent),
            '=' => {
                if self.next_is('=') {
                    self.push(Tok::EqEq);
                    self.i += 2;
                } else if self.next_is('>') {
                    self.push(Tok::FatArrow);
                    self.i += 2;
                } else {
                    self.push(Tok::Eq);
                    self.i += 1;
                }
            }
            '!' => self.op_with_eq(Tok::Neq, Tok::Bang),
            '<' => {
                if self.next_is('<') {
                    self.push(Tok::Shl);
                    self.i += 2;
                } else {
                    self.op_with_eq(Tok::Le, Tok::Lt);
                }
            }
            '>' => {
                if self.next_is('>') {
                    self.push(Tok::Shr);
                    self.i += 2;
                } else {
                    self.op_with_eq(Tok::Ge, Tok::Gt);
                }
            }
            '&' => {
                if self.next_is('&') {
                    self.push(Tok::AmpAmp);
                    self.i += 2;
                } else {
                    self.push(Tok::Amp);
                    self.i += 1;
                }
            }
            '|' => {
                if self.next_is('|') {
                    self.push(Tok::PipePipe);
                    self.i += 2;
                } else {
                    self.push(Tok::Pipe);
                    self.i += 1;
                }
            }
            _ => self.scan_question(),
        }
    }

    /// `a = b` vs `a += b` shape: `op=` two chars ahead or the bare op.
    fn op_with_eq(&mut self, with_eq: Tok, bare: Tok) {
        if self.next_is('=') {
            self.push(with_eq);
            self.i += 2;
        } else {
            self.push(bare);
            self.i += 1;
        }
    }

    /// L1a: '??' = null coalescing; '?.' = optional chaining (only when
    /// not followed by a digit, a float literal can never start with '.',
    /// but a ternary 'a ?. 5' space-form must not eat the dot; digit guard
    /// keeps '?' + '.' separate for any future numeric forms). W06 (D-014):
    /// '?!' = Option/Result propagation. Binds as a POSTFIX operator
    /// (parse_postfix), so it can never collide with the ternary's bare
    /// '?', '?!' is lexed as one token before the '?' fallthrough.
    fn scan_question(&mut self) {
        if self.next_is('?') {
            self.push(Tok::QuestionQuestion);
            self.i += 2;
        } else if self.next_is('.')
            && self.i + 2 < self.n
            && !self.chars[self.i + 2].is_ascii_digit()
        {
            self.push(Tok::QuestionDot);
            self.i += 2;
        } else if self.next_is('!') {
            self.push(Tok::QuestionBang);
            self.i += 2;
        } else {
            self.push(Tok::Question);
            self.i += 1;
        }
    }

    fn next_is(&self, c: char) -> bool {
        self.i + 1 < self.n && self.chars[self.i + 1] == c
    }

    fn next_is2(&self, c: char) -> bool {
        self.i + 2 < self.n && self.chars[self.i + 2] == c
    }
}
