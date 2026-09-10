//! A minimal HTTP/1.1 client over std::net.
//!
//! WHY NOT A CRATE. The relay speaks plain http on its own port, so the only thing an HTTP crate would
//! add here is TLS — and TLS is what turns a Windows cross-build from one command into a project
//! (vendored OpenSSL, or rustls plus a certificate store). This is sixty lines, has no build
//! requirements on any target, and its failure modes are visible.
//!
//! It is NOT a general-purpose client: no redirects, no chunked-encoding edge cases beyond the one the
//! node emits, no connection reuse. It talks to one relay.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

pub struct Relay {
    pub host: String,
    pub port: u16,
}

impl Relay {
    /// Parse `host`, `host:port`, or `http://host:port`.
    pub fn parse(s: &str) -> Result<Relay, String> {
        let s = s.trim().trim_start_matches("http://").trim_end_matches('/');
        let (host, port) = match s.rsplit_once(':') {
            Some((h, p)) => (h.to_string(), p.parse::<u16>().map_err(|_| "bad port")?),
            None => (s.to_string(), 9173),
        };
        if host.is_empty() {
            return Err("relay host is empty".into());
        }
        Ok(Relay { host, port })
    }

    pub fn get(&self, path: &str) -> Result<String, String> {
        self.request("GET", path, None)
    }

    pub fn post_json(&self, path: &str, body: &str) -> Result<String, String> {
        self.request("POST", path, Some(body))
    }

    fn request(&self, method: &str, path: &str, body: Option<&str>) -> Result<String, String> {
        let addr = format!("{}:{}", self.host, self.port);
        let mut stream = TcpStream::connect(&addr).map_err(|e| format!("connect {addr}: {e}"))?;
        stream.set_read_timeout(Some(Duration::from_secs(30))).ok();
        stream.set_write_timeout(Some(Duration::from_secs(30))).ok();

        let mut req = format!(
            "{method} {path} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nUser-Agent: nado-tpm-attest\r\n",
            self.host
        );
        if let Some(b) = body {
            req.push_str("Content-Type: application/json\r\n");
            req.push_str(&format!("Content-Length: {}\r\n", b.len()));
        }
        req.push_str("\r\n");
        if let Some(b) = body {
            req.push_str(b);
        }
        stream.write_all(req.as_bytes()).map_err(|e| format!("write: {e}"))?;

        let mut raw = Vec::new();
        stream.read_to_end(&mut raw).map_err(|e| format!("read: {e}"))?;
        let text = String::from_utf8_lossy(&raw).into_owned();
        let (head, rest) = text
            .split_once("\r\n\r\n")
            .ok_or_else(|| "malformed response (no header terminator)".to_string())?;

        let status: u16 = head
            .lines()
            .next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|c| c.parse().ok())
            .ok_or_else(|| "malformed status line".to_string())?;

        // The node closes the connection, so a chunked body still arrives whole; de-chunk it when the
        // header says so rather than handing the caller size markers it would parse as JSON.
        let body = if head.to_ascii_lowercase().contains("transfer-encoding: chunked") {
            dechunk(rest)?
        } else {
            rest.to_string()
        };

        if !(200..300).contains(&status) {
            return Err(format!("relay returned HTTP {status}: {}", body.trim().chars().take(300).collect::<String>()));
        }
        Ok(body)
    }
}

fn dechunk(mut s: &str) -> Result<String, String> {
    let mut out = String::new();
    loop {
        let (size_line, rest) = s.split_once("\r\n").ok_or("truncated chunk header")?;
        let n = usize::from_str_radix(size_line.trim().split(';').next().unwrap_or("0"), 16)
            .map_err(|_| "bad chunk size")?;
        if n == 0 {
            return Ok(out);
        }
        if rest.len() < n {
            return Err("truncated chunk body".into());
        }
        out.push_str(&rest[..n]);
        s = rest.get(n + 2..).ok_or("truncated chunk terminator")?;
    }
}
