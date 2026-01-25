"""Tests for subscription module core functionality."""

from unittest.mock import Mock

from actingweb.subscription import Subscription, Subscriptions


class TestSubscriptionClassInitialization:
    """Test Subscription class initialization."""

    def test_subscription_init_with_all_params(self):
        """Test Subscription initialization with all parameters."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {}
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            callback=True,
            config=mock_config,
        )

        assert sub.actor_id == "test_actor"
        assert sub.peerid == "peer123"
        assert sub.subid == "sub456"
        assert sub.callback is True
        assert sub.config == mock_config

    def test_subscription_init_minimal(self):
        """Test Subscription initialization with minimal parameters."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(actor_id="test_actor", config=mock_config)

        assert sub.actor_id == "test_actor"
        assert sub.peerid is None
        assert sub.subid is None
        assert sub.callback is False

    def test_subscription_init_no_actor_id(self):
        """Test Subscription initialization without actor_id returns early."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(config=mock_config)

        assert sub.subscription == {}

    def test_subscription_init_without_config(self):
        """Test Subscription initialization without config."""
        sub = Subscription(actor_id="test_actor")

        assert sub.handle is None
        assert sub.config is None


class TestSubscriptionCRUD:
    """Test Subscription CRUD operations."""

    def _create_subscription_with_mock(self) -> tuple[Subscription, Mock, Mock]:
        """Helper to create Subscription with mocked db."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {}
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            config=mock_config,
        )
        return sub, mock_db_subscription, mock_config

    def test_subscription_get_returns_subscription(self):
        """Test subscription.get() returns existing subscription."""
        mock_config = Mock()
        mock_db_subscription = Mock()

        mock_sub_data = {
            "id": "test_actor",
            "subscriptionid": "sub456",
            "peerid": "peer123",
            "target": "properties",
            "sequence": 5,
        }
        mock_db_subscription.get.return_value = mock_sub_data
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )
        result = sub.get()

        assert result == mock_sub_data
        assert result["target"] == "properties"
        assert result["sequence"] == 5

    def test_subscription_get_empty_when_not_found(self):
        """Test subscription.get() returns empty dict when not found."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = None
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )
        result = sub.get()

        assert result == {}

    def test_subscription_create_success(self):
        """Test subscription.create() creates new subscription."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {}
        mock_db_subscription.create.return_value = True
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription
        mock_config.root = "https://example.com/"
        mock_config.new_uuid.return_value = "generated_sub_id_123"

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            config=mock_config,
        )

        result = sub.create(
            target="properties",
            subtarget="config",
            resource="notes",
            granularity="fine",
            seqnr=1,
        )

        assert result is True
        mock_db_subscription.create.assert_called_once()
        assert sub.subscription is not None  # Type narrowing for pyright
        assert sub.subscription["target"] == "properties"
        assert sub.subscription["subtarget"] == "config"

    def test_subscription_create_fails_when_exists(self):
        """Test subscription.create() fails when subscription already exists."""
        mock_config = Mock()
        mock_db_subscription = Mock()

        # Subscription already exists in db
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "existing_sub",
            "peerid": "peer123",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="existing_sub",
            config=mock_config,
        )

        result = sub.create(target="properties")

        assert result is False
        mock_db_subscription.create.assert_not_called()

    def test_subscription_delete_success(self):
        """Test subscription.delete() removes subscription."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_db_subscription.delete.return_value = True
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff_list = Mock()
        mock_config.DbSubscriptionDiff.DbSubscriptionDiffList.return_value = (
            mock_diff_list
        )

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.delete()

        assert result is True
        mock_db_subscription.delete.assert_called_once()


class TestSubscriptionDiffs:
    """Test diff management methods."""

    def test_subscription_increase_seq(self):
        """Test increase_seq increments sequence number."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_sub_data = {
            "id": "test_actor",
            "subscriptionid": "sub456",
            "peerid": "peer123",
            "sequence": 5,
        }
        mock_db_subscription.get.return_value = mock_sub_data
        mock_db_subscription.modify.return_value = True
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.increase_seq()

        assert result is True
        assert sub.subscription is not None  # Type narrowing for pyright
        assert sub.subscription["sequence"] == 6
        mock_db_subscription.modify.assert_called_once_with(seqnr=6)

    def test_subscription_add_diff(self):
        """Test add_diff creates new diff entry."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_sub_data = {
            "id": "test_actor",
            "subscriptionid": "sub456",
            "peerid": "peer123",
            "sequence": 5,
        }
        mock_db_subscription.get.return_value = mock_sub_data
        mock_db_subscription.modify.return_value = True
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff = Mock()
        mock_diff.get.return_value = {"seqnr": 5, "diff": "blob_data"}
        mock_config.DbSubscriptionDiff.DbSubscriptionDiff.return_value = mock_diff

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.add_diff(blob="test_blob_data")

        assert result is not None
        mock_diff.create.assert_called_once()

    def test_subscription_add_diff_without_blob(self):
        """Test add_diff returns False without blob."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.add_diff(blob=None)

        assert result is False

    def test_subscription_get_diff(self):
        """Test get_diff retrieves specific diff by seqnr."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff = Mock()
        mock_diff.get.return_value = {"seqnr": 3, "diff": "diff_data"}
        mock_config.DbSubscriptionDiff.DbSubscriptionDiff.return_value = mock_diff

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.get_diff(seqnr=3)

        assert result is not None
        mock_diff.get.assert_called()

    def test_subscription_get_diff_zero_seqnr(self):
        """Test get_diff returns None for seqnr=0."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.get_diff(seqnr=0)

        assert result is None

    def test_subscription_get_diffs(self):
        """Test get_diffs retrieves all diffs for subscription."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff_list = Mock()
        mock_diffs = [
            {"seqnr": 1, "diff": "diff1"},
            {"seqnr": 2, "diff": "diff2"},
            {"seqnr": 3, "diff": "diff3"},
        ]
        mock_diff_list.fetch.return_value = mock_diffs
        mock_config.DbSubscriptionDiff.DbSubscriptionDiffList.return_value = (
            mock_diff_list
        )

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.get_diffs()

        assert result == mock_diffs
        assert len(result) == 3

    def test_subscription_clear_diff(self):
        """Test clear_diff removes specific diff."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff = Mock()
        mock_diff.delete.return_value = True
        mock_config.DbSubscriptionDiff.DbSubscriptionDiff.return_value = mock_diff

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        result = sub.clear_diff(seqnr=3)

        assert result is True
        mock_diff.delete.assert_called_once()

    def test_subscription_clear_diffs(self):
        """Test clear_diffs removes all diffs up to seqnr."""
        mock_config = Mock()
        mock_db_subscription = Mock()
        mock_db_subscription.get.return_value = {
            "id": "test_actor",
            "subscriptionid": "sub456",
        }
        mock_config.DbSubscription.DbSubscription.return_value = mock_db_subscription

        mock_diff_list = Mock()
        mock_config.DbSubscriptionDiff.DbSubscriptionDiffList.return_value = (
            mock_diff_list
        )

        sub = Subscription(
            actor_id="test_actor",
            peerid="peer123",
            subid="sub456",
            config=mock_config,
        )

        sub.clear_diffs(seqnr=5)

        mock_diff_list.delete.assert_called_once_with(seqnr=5)


class TestSubscriptionsCollection:
    """Test Subscriptions collection class."""

    def test_subscriptions_init_with_actor_id(self):
        """Test Subscriptions initialization with actor_id."""
        mock_config = Mock()
        mock_db_sub_list = Mock()
        mock_db_sub_list.fetch.return_value = []
        mock_config.DbSubscription.DbSubscriptionList.return_value = mock_db_sub_list

        subs = Subscriptions(actor_id="test_actor", config=mock_config)

        assert subs.actor_id == "test_actor"

    def test_subscriptions_init_without_actor_id(self):
        """Test Subscriptions initialization without actor_id."""
        mock_config = Mock()

        subs = Subscriptions(actor_id=None, config=mock_config)

        assert subs.list is None

    def test_subscriptions_fetch_retrieves_all(self):
        """Test subscriptions.fetch() retrieves all subscriptions."""
        mock_config = Mock()
        mock_db_sub_list = Mock()

        mock_subs = [
            {"subscriptionid": "sub1", "peerid": "peer1"},
            {"subscriptionid": "sub2", "peerid": "peer2"},
        ]
        mock_db_sub_list.fetch.return_value = mock_subs
        mock_config.DbSubscription.DbSubscriptionList.return_value = mock_db_sub_list

        subs = Subscriptions(actor_id="test_actor", config=mock_config)
        result = subs.fetch()

        assert result == mock_subs
        assert result is not None and len(result) == 2

    def test_subscriptions_delete_removes_all_with_diffs(self):
        """Test subscriptions.delete() removes all subscriptions and their diffs."""
        mock_config = Mock()
        mock_db_sub_list = Mock()

        mock_subs = [
            {"subscriptionid": "sub1", "peerid": "peer1"},
            {"subscriptionid": "sub2", "peerid": "peer2"},
        ]
        mock_db_sub_list.fetch.return_value = mock_subs
        mock_config.DbSubscription.DbSubscriptionList.return_value = mock_db_sub_list

        mock_diff_list = Mock()
        mock_config.DbSubscriptionDiff.DbSubscriptionDiffList.return_value = (
            mock_diff_list
        )

        subs = Subscriptions(actor_id="test_actor", config=mock_config)
        result = subs.delete()

        assert result is True
        mock_db_sub_list.delete.assert_called_once()
        # Verify diffs were fetched and deleted for each subscription
        assert mock_diff_list.delete.call_count == 2

    def test_subscriptions_delete_without_list(self):
        """Test subscriptions.delete() returns False when list is None."""
        mock_config = Mock()

        subs = Subscriptions(actor_id=None, config=mock_config)
        result = subs.delete()

        assert result is False
