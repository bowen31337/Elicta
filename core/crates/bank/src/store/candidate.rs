/// One candidate question in a meeting's synced bank (architecture §3.6),
/// as it lives on the device: everything the local ranking/phrasing/
/// retrieval path needs, with no field requiring a network call to fill in.
///
/// Mirrors `apps/service`'s `compiler/bank/models.py::BankCandidate` plus
/// the columns architecture §3.6 lists that ranking (`authority_match`) and
/// retrieval (`embedding`) read directly, rather than the full compiled-
/// candidate row shape — this store only needs to round-trip what the
/// on-device runtime actually consumes.
#[derive(Debug, Clone, PartialEq)]
pub struct BankCandidate {
    pub id: String,
    pub template_section: String,
    pub phrasing: String,
    pub stub: String,
    pub lang: String,
    pub priority: i64,
    pub authority_match: f32,
    pub source_doc: Option<String>,
    pub trigger_types: Vec<String>,
    pub requires: Vec<String>,
    pub embedding: Vec<f32>,
    pub inherited_from_open_question: bool,
}
