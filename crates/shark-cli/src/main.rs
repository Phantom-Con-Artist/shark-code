use shark_core::Engine;
use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
};
const MAX_REQUEST: usize = 8 * 1024 * 1024;
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let root = match args.next().as_deref() {
        Some("--workspace") => PathBuf::from(args.next().ok_or("--workspace needs a directory")?),
        Some("--help") | Some("-h") => {
            println!(
                "shark-backend --workspace PATH\nJSON requests on stdin, one per line. Start with {{\"id\":1,\"method\":\"capabilities\"}}."
            );
            return Ok(());
        }
        None => std::env::current_dir()?,
        _ => return Err("Usage: shark-backend --workspace PATH".into()),
    };
    if args.next().is_some() {
        return Err("Unexpected argument".into());
    }
    let engine = Engine::open(root)?;
    let mut stdin = io::stdin().lock();
    let mut stdout = io::stdout().lock();
    let mut line = Vec::new();
    loop {
        // fill_buf avoids allocating an unbounded line from an agent process.
        line.clear();
        let mut oversized = false;
        loop {
            let buffer = stdin.fill_buf()?;
            if buffer.is_empty() {
                break;
            }
            let count = buffer
                .iter()
                .position(|b| *b == b'\n')
                .map_or(buffer.len(), |n| n + 1);
            let done = buffer[count - 1] == b'\n';
            if line.len() + count > MAX_REQUEST {
                oversized = true;
            }
            if !oversized {
                line.extend_from_slice(&buffer[..count]);
            }
            stdin.consume(count);
            if done {
                break;
            }
        }
        if line.is_empty() && !oversized {
            break;
        }
        let response = if oversized {
            serde_json::json!({"id":null,"error":{"code":"request_too_large","message":"Requests must be under 8 MiB"}})
        } else {
            match std::str::from_utf8(&line) {
                Ok(text) => engine.dispatch(text),
                Err(_) => {
                    serde_json::json!({"id":null,"error":{"code":"invalid_utf8","message":"Requests must be UTF-8"}})
                }
            }
        };
        serde_json::to_writer(&mut stdout, &response)?;
        stdout.write_all(b"\n")?;
        stdout.flush()?;
    }
    Ok(())
}
