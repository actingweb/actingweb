"""
Simplified trust relationship management for ActingWeb actors.
"""

from typing import List, Dict, Any, Optional, Union
from ..actor import Actor as CoreActor


class TrustRelationship:
    """Represents a trust relationship with another actor."""
    
    def __init__(self, data: Dict[str, Any]):
        self._data = data
        
    @property
    def peer_id(self) -> str:
        """ID of the peer actor."""
        return self._data.get("peerid", "")
        
    @property
    def base_uri(self) -> str:
        """Base URI of the peer actor."""
        return self._data.get("baseuri", "")
        
    @property
    def relationship(self) -> str:
        """Type of relationship (friend, partner, etc.)."""
        return self._data.get("relationship", "")
        
    @property
    def approved(self) -> bool:
        """Whether this side has approved the relationship."""
        return self._data.get("approved", False)
        
    @property
    def peer_approved(self) -> bool:
        """Whether the peer has approved the relationship."""
        return self._data.get("peer_approved", False)
        
    @property
    def verified(self) -> bool:
        """Whether the relationship has been verified."""
        return self._data.get("verified", False)
        
    @property
    def is_active(self) -> bool:
        """Whether the relationship is fully active (approved by both sides)."""
        return self.approved and self.peer_approved and self.verified
        
    @property
    def description(self) -> str:
        """Description of the relationship."""
        return self._data.get("desc", "")
        
    @property
    def peer_type(self) -> str:
        """Type of the peer actor."""
        return self._data.get("type", "")
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self._data.copy()


class TrustManager:
    """
    Simplified interface for managing trust relationships.
    
    Example usage:
        # Create trust with another actor
        relationship = actor.trust.create_relationship(
            peer_url="https://peer.example.com/actor123",
            relationship="friend"
        )
        
        # List all relationships
        for rel in actor.trust.relationships:
            print(f"Trust with {rel.peer_id}: {rel.relationship}")
            
        # Find specific relationship
        friend = actor.trust.find_relationship(relationship="friend")
        
        # Approve a relationship
        actor.trust.approve_relationship(peer_id="peer123")
    """
    
    def __init__(self, core_actor: CoreActor):
        self._core_actor = core_actor
        
    @property
    def relationships(self) -> List[TrustRelationship]:
        """Get all trust relationships."""
        relationships = self._core_actor.get_trust_relationships()
        return [TrustRelationship(rel) for rel in relationships if isinstance(rel, dict)]
        
    def find_relationship(self, peer_id: str = "", relationship: str = "", 
                         trust_type: str = "") -> Optional[TrustRelationship]:
        """Find a specific trust relationship."""
        relationships = self._core_actor.get_trust_relationships(
            peerid=peer_id, 
            relationship=relationship, 
            trust_type=trust_type
        )
        if relationships and isinstance(relationships[0], dict):
            return TrustRelationship(relationships[0])
        return None
        
    def get_relationship(self, peer_id: str) -> Optional[TrustRelationship]:
        """Get relationship with specific peer."""
        rel_data = self._core_actor.get_trust_relationship(peerid=peer_id)
        if rel_data and isinstance(rel_data, dict):
            return TrustRelationship(rel_data)
        return None
        
    def create_relationship(self, peer_url: str, relationship: str = "friend", 
                          secret: str = "", description: str = "") -> Optional[TrustRelationship]:
        """Create a new trust relationship with another actor."""
        if not secret:
            secret = self._core_actor.config.new_token() if self._core_actor.config else ""
            
        rel_data = self._core_actor.create_reciprocal_trust(
            url=peer_url,
            secret=secret,
            desc=description,
            relationship=relationship
        )
        
        if rel_data and isinstance(rel_data, dict):
            return TrustRelationship(rel_data)
        return None
        
    def approve_relationship(self, peer_id: str) -> bool:
        """Approve a trust relationship."""
        relationship = self.get_relationship(peer_id)
        if not relationship:
            return False
            
        result = self._core_actor.modify_trust_and_notify(
            peerid=peer_id,
            relationship=relationship.relationship,
            approved=True
        )
        return bool(result)
        
    def delete_relationship(self, peer_id: str) -> bool:
        """Delete a trust relationship."""
        result = self._core_actor.delete_reciprocal_trust(peerid=peer_id, delete_peer=True)
        return bool(result)
        
    def delete_all_relationships(self) -> bool:
        """Delete all trust relationships."""
        result = self._core_actor.delete_reciprocal_trust(delete_peer=True)
        return bool(result)
        
    @property
    def active_relationships(self) -> List[TrustRelationship]:
        """Get all active (approved and verified) relationships."""
        return [rel for rel in self.relationships if rel.is_active]
        
    @property
    def pending_relationships(self) -> List[TrustRelationship]:
        """Get all pending (not yet approved by both sides) relationships."""
        return [rel for rel in self.relationships if not rel.is_active]
        
    def get_peers_by_relationship(self, relationship: str) -> List[TrustRelationship]:
        """Get all peers with a specific relationship type."""
        return [rel for rel in self.relationships if rel.relationship == relationship]
        
    def has_relationship_with(self, peer_id: str) -> bool:
        """Check if there's a relationship with the given peer."""
        return self.get_relationship(peer_id) is not None
        
    def is_trusted_peer(self, peer_id: str) -> bool:
        """Check if peer is trusted (has active relationship)."""
        relationship = self.get_relationship(peer_id)
        return relationship is not None and relationship.is_active