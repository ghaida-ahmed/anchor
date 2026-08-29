"""A small course corpus and question set for judging retrieval quality.

The questions are deliberately phrased the way a student would ask them, not the
way the source text is written. Several share almost no distinctive vocabulary with
the passage that answers them — "turn a website name into a numeric address" versus
"resolves domain names into IP addresses" — because keyword overlap would prove
nothing about semantic retrieval.
"""

from dataclasses import dataclass

# Each entry is (filename, page texts). Written to resemble real lecture notes.
CORPUS: list[tuple[str, list[str]]] = [
    (
        "Lecture 04 - Transport Layer.pdf",
        [
            "The transport layer provides process-to-process communication. TCP offers "
            "a reliable, connection-oriented byte stream, while UDP offers an "
            "unreliable, connectionless datagram service with lower overhead.",
            "Reliability in TCP rests on sequence numbers and acknowledgements. Each "
            "segment carries a sequence number; the receiver acknowledges the highest "
            "contiguous byte received. Unacknowledged segments are retransmitted after "
            "a timeout derived from the smoothed round trip time.",
            "Flow control prevents a fast sender from overwhelming a slow receiver. The "
            "receiver advertises a window indicating how much buffer space remains, and "
            "the sender may have at most that many unacknowledged bytes outstanding. "
            "This sliding window slides forward as acknowledgements arrive.",
        ],
    ),
    (
        "Lecture 05 - Congestion Control.pdf",
        [
            "Congestion arises when the aggregate demand on a link exceeds its "
            "capacity, causing queues to build and eventually packets to be discarded.",
            "TCP treats loss as a congestion signal. On detecting loss the sender "
            "reduces its congestion window multiplicatively, typically halving it, "
            "which quickly drains the bottleneck queue. During congestion avoidance "
            "the window grows by roughly one segment per round trip. This additive "
            "increase multiplicative decrease behaviour, known as AIMD, causes "
            "competing flows to converge on a roughly fair share of the bottleneck.",
            "Slow start ramps up quickly at the beginning of a connection, doubling "
            "the window each round trip until a threshold is reached, after which the "
            "connection enters the slower additive increase phase.",
        ],
    ),
    (
        "Lecture 07 - Naming and Addressing.pdf",
        [
            "The Domain Name System is a distributed hierarchical database. It "
            "translates the human readable names people type into the numeric "
            "addresses that packets are actually routed to. A resolver queries a root "
            "server, then a top level domain server, then the authoritative server for "
            "the zone, caching answers along the way to reduce future lookups.",
            "Classless inter-domain routing replaced fixed address classes with a "
            "prefix length. An address written as 192.0.2.0/24 reserves the first 24 "
            "bits for the network portion, leaving the remainder to identify hosts. "
            "Dividing an allocation into smaller prefixes is called subnetting.",
        ],
    ),
    (
        "Lecture 09 - Memory Safety.pdf",
        [
            "A buffer overflow happens when a program writes more data into a region "
            "than was allocated for it, corrupting whatever lies beyond. On the stack "
            "this can overwrite the saved return address and divert execution.",
            "Several mitigations raise the cost of exploitation. A stack canary is a "
            "random value placed before the saved return address and checked before "
            "returning; corruption is detected and the process aborts. Address space "
            "layout randomisation makes the location of code and data unpredictable, "
            "and marking the stack non-executable prevents injected code from running.",
        ],
    ),
]


@dataclass(frozen=True)
class EvaluationQuestion:
    question: str
    # Filename the answer should be retrieved from.
    expected_document: str
    # Page within that document, 1-based.
    expected_page: int
    # True when the question shares little distinctive vocabulary with the source,
    # so answering it correctly requires semantic rather than lexical matching.
    paraphrased: bool


QUESTIONS: list[EvaluationQuestion] = [
    EvaluationQuestion(
        question="Why does TCP slow down when packets get dropped?",
        expected_document="Lecture 05 - Congestion Control.pdf",
        expected_page=2,
        paraphrased=True,
    ),
    EvaluationQuestion(
        question="How does a computer turn a website name into a numeric address?",
        expected_document="Lecture 07 - Naming and Addressing.pdf",
        expected_page=1,
        paraphrased=True,
    ),
    EvaluationQuestion(
        question="What stops an attacker from writing past the end of an array?",
        expected_document="Lecture 09 - Memory Safety.pdf",
        expected_page=2,
        paraphrased=True,
    ),
    EvaluationQuestion(
        question="How does a sender avoid swamping a receiver that cannot keep up?",
        expected_document="Lecture 04 - Transport Layer.pdf",
        expected_page=3,
        paraphrased=True,
    ),
    EvaluationQuestion(
        question="What does the /24 in an IP address mean?",
        expected_document="Lecture 07 - Naming and Addressing.pdf",
        expected_page=2,
        paraphrased=True,
    ),
    EvaluationQuestion(
        question="What is AIMD?",
        expected_document="Lecture 05 - Congestion Control.pdf",
        expected_page=2,
        paraphrased=False,
    ),
    EvaluationQuestion(
        question="How does TCP achieve reliable delivery?",
        expected_document="Lecture 04 - Transport Layer.pdf",
        expected_page=2,
        paraphrased=False,
    ),
    EvaluationQuestion(
        question="What is a stack canary?",
        expected_document="Lecture 09 - Memory Safety.pdf",
        expected_page=2,
        paraphrased=False,
    ),
]

# Questions no document in the corpus answers. Retrieval should surface nothing
# above the relevance threshold, and `ask` should decline rather than invent.
OUT_OF_SCOPE_QUESTIONS = [
    "What temperature should I proof sourdough at?",
    "Who won the 1998 football world cup?",
]
