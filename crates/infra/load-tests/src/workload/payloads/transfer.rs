use alloy_network::TransactionBuilder;
use alloy_primitives::{Address, U256};
use alloy_rpc_types::TransactionRequest;
use async_trait::async_trait;

use super::Payload;
use crate::workload::SeededRng;

/// Generates simple ETH transfer transactions.
#[derive(Debug, Clone)]
pub struct TransferPayload {
    /// Minimum value to transfer.
    pub min_value: U256,
    /// Maximum value to transfer.
    pub max_value: U256,
    /// Whether each transaction uses its sender as the recipient.
    pub self_recipient: bool,
}

impl TransferPayload {
    /// Creates a new transfer payload with min and max values.
    pub const fn new(min_value: U256, max_value: U256) -> Self {
        Self { min_value, max_value, self_recipient: false }
    }

    /// Creates a transfer payload with a fixed value.
    pub const fn fixed(value: U256) -> Self {
        Self { min_value: value, max_value: value, self_recipient: false }
    }
}

impl Default for TransferPayload {
    fn default() -> Self {
        Self {
            min_value: U256::from(1_000u64),
            max_value: U256::from(100_000u64),
            self_recipient: false,
        }
    }
}

#[async_trait]
impl Payload for TransferPayload {
    fn name(&self) -> &'static str {
        "transfer"
    }

    fn uses_runner_recipient(&self) -> bool {
        !self.self_recipient
    }

    fn generate(&self, rng: &mut SeededRng, from: Address, to: Address) -> TransactionRequest {
        let value = if self.min_value == self.max_value {
            self.min_value
        } else {
            let min: u128 =
                self.min_value.try_into().expect("validated <= u128::MAX at config parse");
            let max: u128 =
                self.max_value.try_into().expect("validated <= u128::MAX at config parse");
            U256::from(rng.gen_range(min..=max))
        };

        let recipient = if self.self_recipient { from } else { to };
        TransactionRequest::default().with_to(recipient).with_value(value).with_gas_limit(21_000)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transfer_payload_name_and_recipient_flags() {
        let payload = TransferPayload::default();
        assert_eq!(payload.name(), "transfer");
        assert!(payload.uses_runner_recipient());
        assert!(!payload.uses_pair_recipient());
    }

    #[test]
    fn zero_value_self_transfer_targets_sender() {
        let mut payload = TransferPayload::fixed(U256::ZERO);
        payload.self_recipient = true;
        let mut rng = SeededRng::new(1);
        let from = Address::repeat_byte(0x11);

        let request = payload.generate(&mut rng, from, Address::repeat_byte(0x22));

        assert!(!payload.uses_runner_recipient());
        assert_eq!(request.to.unwrap().to(), Some(&from));
        assert_eq!(request.value, Some(U256::ZERO));
    }
}
