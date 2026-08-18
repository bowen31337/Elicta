//! Byte encoding for a candidate's embedding vector (architecture §3.6:
//! "Local SQLite with a vector index ... brute-force cosine is
//! sub-millisecond and an approximate index is unnecessary complexity").
//!
//! No vector index library is involved here — an embedding is just a flat
//! `Vec<f32>` written as a little-endian byte blob, which is all a
//! brute-force cosine scan over a few hundred candidates needs.

/// Encodes an embedding vector as a little-endian byte blob for storage in
/// the `embedding` BLOB column.
pub fn encode(embedding: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(embedding.len() * 4);
    for value in embedding {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

/// Decodes a little-endian byte blob back into an embedding vector.
///
/// Returns `None` if `bytes` isn't a whole number of `f32`s — a corrupt
/// row this store never itself produces, so a caller can treat it as a
/// data-integrity error rather than a normal decode outcome.
pub fn decode(bytes: &[u8]) -> Option<Vec<f32>> {
    if !bytes.len().is_multiple_of(4) {
        return None;
    }
    Some(
        bytes
            .chunks_exact(4)
            .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_an_embedding_vector() {
        let embedding = vec![0.0, 1.5, -3.25, f32::MAX, f32::MIN];
        let bytes = encode(&embedding);
        assert_eq!(decode(&bytes), Some(embedding));
    }

    #[test]
    fn round_trips_an_empty_embedding() {
        let bytes = encode(&[]);
        assert_eq!(decode(&bytes), Some(vec![]));
    }

    #[test]
    fn rejects_a_blob_whose_length_is_not_a_multiple_of_four() {
        assert_eq!(decode(&[0u8, 1, 2]), None);
    }
}
