//! Parser for the S1 strict core: items and statements (STRICT-CORE §2.1,
//! §2.2). Expressions live in parse_expr.rs. Rejections carry the §4 rule
//! wording; legacy keywords get pointed diagnostics, never generic ones.

use super::StrictError;
use super::ast::{FnDef, Stmt};
use super::lex::{Tok, Token};
use crate::mir::MirType;

/// Legacy `fn` synonyms: item-position spellings the strict core rejects
/// with the §2.1 "use fn" diagnostic (STRICT-CORE §2.5).
pub const LEGACY_FN_SYNONYMS: &[&str] =
    &["gene", "func", "fun", "def", "funct", "sub", "lambda", "proc"];

/// Other legacy constructs refused BY NAME so the diagnostic points at the
/// subset boundary instead of a generic parse error.
pub const LEGACY_CONSTRUCTS: &[&str] = &[
    "phenotype", "stress", "rescue", "seq", "sequence", "channel", "select",
    "cell", "network", "when", "match", "for", "uses", "provides", "emit",
    "homeostasis", "quorum", "methylation", "rna", "grn", "loop", "break",
    "continue", "spawn", "await", "suspend", "yield",
];

pub struct Parser {
    pub toks: Vec<Token>,
    pub pos: usize,
}

impl Parser {
    pub fn peek(&self) -> &Tok {
        &self.toks[self.pos].tok
    }

    pub fn line(&self) -> usize {
        self.toks[self.pos].line
    }

    pub fn bump(&mut self) -> Token {
        let t = self.toks[self.pos].clone();
        if self.pos + 1 < self.toks.len() {
            self.pos += 1;
        }
        t
    }

    pub fn expect(&mut self, want: &Tok, what: &str) -> Result<usize, StrictError> {
        if self.peek() == want {
            Ok(self.bump().line)
        } else {
            Err(self.unexpected(what))
        }
    }

    pub fn unexpected(&self, what: &str) -> StrictError {
        let (tok, line) = (&self.toks[self.pos].tok, self.toks[self.pos].line);
        if let Tok::Ident(name) = tok {
            if LEGACY_FN_SYNONYMS.contains(&name.as_str()) {
                return StrictError::new(
                    line,
                    format!("legacy function keyword '{name}' — strict core uses fn (STRICT-CORE §2.1)"),
                );
            }
            if LEGACY_CONSTRUCTS.contains(&name.as_str()) {
                return StrictError::new(line, format!("'{name}' is {}", pointed_outside()));
            }
        }
        StrictError::new(line, format!("expected {what}, found {}", show_tok(tok)))
    }

    pub fn parse_file(&mut self) -> Result<Vec<FnDef>, StrictError> {
        let mut fns = Vec::new();
        while *self.peek() != Tok::Eof {
            match self.peek() {
                Tok::Fn => fns.push(self.parse_fn()?),
                Tok::Ident(name) if LEGACY_FN_SYNONYMS.contains(&name.as_str()) => {
                    let line = self.line();
                    let name = name.clone();
                    return Err(StrictError::new(
                        line,
                        format!("legacy function keyword '{name}' — strict core uses fn (STRICT-CORE §2.1)"),
                    ));
                }
                Tok::Ident(name) if LEGACY_CONSTRUCTS.contains(&name.as_str()) => {
                    let line = self.line();
                    let name = name.clone();
                    return Err(StrictError::new(line, format!("'{name}' is {}", pointed_outside())));
                }
                _ => {
                    let line = self.line();
                    return Err(StrictError::new(
                        line,
                        "the strict core file level is `fn` definitions only (STRICT-CORE §2.1)",
                    ));
                }
            }
        }
        Ok(fns)
    }

    pub fn parse_fn(&mut self) -> Result<FnDef, StrictError> {
        let line = self.expect(&Tok::Fn, "`fn`")?;
        let name = match self.bump().tok {
            Tok::Ident(n) => n,
            _ => return Err(self.unexpected("the function name")),
        };
        self.expect(&Tok::LParen, "`(`")?;
        let params = self.parse_params()?;
        self.expect(&Tok::RParen, "`)`")?;
        let ret = self.parse_opt_ret_type()?;
        let body = self.parse_block()?;
        Ok(FnDef { name, params, ret, body, line })
    }

    fn parse_params(&mut self) -> Result<Vec<(String, MirType)>, StrictError> {
        let mut params = Vec::new();
        if *self.peek() == Tok::RParen {
            return Ok(params);
        }
        loop {
            let pname = match self.bump().tok {
                Tok::Ident(n) => n,
                _ => return Err(self.unexpected("a parameter name")),
            };
            self.expect(&Tok::Colon, "`:` before the parameter type")?;
            let pty = self.parse_type()?;
            params.push((pname, pty));
            if *self.peek() != Tok::Comma {
                return Ok(params);
            }
            self.bump();
        }
    }

    /// Return type: spec-canonical `: T`, corpus-compatible `-> T`. The
    /// intersection slice files use `->` because the legacy parser honors
    /// `->` and silently ignores `:`.
    fn parse_opt_ret_type(&mut self) -> Result<MirType, StrictError> {
        match self.peek() {
            Tok::Colon | Tok::Arrow => {
                self.bump();
                self.parse_type()
            }
            _ => Ok(MirType::Unit),
        }
    }

    pub fn parse_type(&mut self) -> Result<MirType, StrictError> {
        let line = self.line();
        match self.bump().tok {
            Tok::Ident(t) => type_by_name(&t, line),
            _ => Err(self.unexpected("a type name")),
        }
    }

    pub fn parse_block(&mut self) -> Result<Vec<Stmt>, StrictError> {
        self.expect(&Tok::LBrace, "`{`")?;
        let mut stmts = Vec::new();
        loop {
            match self.peek() {
                Tok::RBrace => {
                    self.bump();
                    return Ok(stmts);
                }
                Tok::Eof => return Err(self.unexpected("`}` before end of file")),
                _ => stmts.push(self.parse_stmt()?),
            }
        }
    }

    pub fn parse_stmt(&mut self) -> Result<Stmt, StrictError> {
        let line = self.line();
        match self.peek().clone() {
            Tok::Let => self.parse_let(line),
            Tok::If => self.parse_if(line),
            Tok::While => self.parse_while(line),
            Tok::Return => self.parse_return(line),
            Tok::Ident(_) => self.parse_ident_stmt(line),
            _ => Err(self.unexpected("a statement (let | assignment | if | while | return | expression)")),
        }
    }

    fn parse_let(&mut self, line: usize) -> Result<Stmt, StrictError> {
        self.bump();
        let name = match self.bump().tok {
            Tok::Ident(n) => n,
            _ => return Err(self.unexpected("the binding name after `let`")),
        };
        self.expect(&Tok::Colon, "`:` before the binding type")?;
        let ty = self.parse_type()?;
        self.expect(&Tok::Assign, "`=` (typed `let` always has an initializer)")?;
        let init = self.parse_expr()?;
        Ok(Stmt::Let { name, ty, init, line })
    }

    fn parse_if(&mut self, line: usize) -> Result<Stmt, StrictError> {
        self.bump();
        let cond = self.parse_expr()?;
        let then = self.parse_block()?;
        let els = if *self.peek() == Tok::Else {
            self.bump();
            if *self.peek() == Tok::If {
                vec![self.parse_stmt()?]
            } else {
                self.parse_block()?
            }
        } else {
            Vec::new()
        };
        Ok(Stmt::If { cond, then, els, line })
    }

    fn parse_while(&mut self, line: usize) -> Result<Stmt, StrictError> {
        self.bump();
        let cond = self.parse_expr()?;
        let body = self.parse_block()?;
        Ok(Stmt::While { cond, body, line })
    }

    fn parse_return(&mut self, line: usize) -> Result<Stmt, StrictError> {
        self.bump();
        let val = if matches!(self.peek(), Tok::RBrace) {
            None
        } else {
            Some(self.parse_expr()?)
        };
        Ok(Stmt::Return { val, line })
    }

    /// IDENT `=` expr is assignment; a bare expression is a statement. The
    /// one-token lookahead decides before either path commits.
    fn parse_ident_stmt(&mut self, line: usize) -> Result<Stmt, StrictError> {
        if self.toks[self.pos + 1].tok == Tok::Assign {
            let name = match self.bump().tok {
                Tok::Ident(n) => n,
                _ => unreachable!("peeked Ident"),
            };
            self.bump();
            let val = self.parse_expr()?;
            return Ok(Stmt::Assign { name, val, line });
        }
        Ok(Stmt::Expr(self.parse_expr()?))
    }
}

fn type_by_name(t: &str, line: usize) -> Result<MirType, StrictError> {
    match t {
        "Int" => Ok(MirType::Int),
        "Float" => Ok(MirType::Float),
        "Bool" => Ok(MirType::Bool),
        "Str" => Ok(MirType::Str),
        "Unit" => Ok(MirType::Unit),
        // S1-Core-1 growth: declared types with a planned home; refuse with
        // the pointer instead of a silent error
        other => Err(StrictError::new(
            line,
            format!("unknown type '{other}' — the S1 surface is Int | Float | Bool | Str | Unit (STRICT-CORE §2.4)"),
        )),
    }
}

fn pointed_outside() -> &'static str {
    "outside the strict core (see docs/design/STRICT-CORE.md §2.5)"
}

fn show_tok(tok: &Tok) -> String {
    match tok {
        Tok::Ident(s) => format!("identifier '{s}'"),
        Tok::Int(v) => format!("number {v}"),
        Tok::Float(v) => format!("number {v}"),
        Tok::Str(_) => "string literal".to_string(),
        Tok::Eof => "end of file".to_string(),
        other => format!("token {other:?}"),
    }
}
