# Subtask 5: Integration with Main Bot and CLI

## Overview
This subtask focuses on seamlessly integrating the EIP-7702 bundled transaction system with the existing futarchy arbitrage bot infrastructure. It includes updating the CLI, maintaining backward compatibility, implementing feature flags, and creating a smooth migration path from sequential to bundled execution.

## Objectives
1. Integrate bundled transactions into `pectra_bot.py` main loop
2. Update CLI to support bundle-specific options
3. Implement feature flags for gradual rollout
4. Create migration utilities and documentation
5. Establish monitoring and alerting for bundled operations

## Technical Requirements

### Integration Points
- Preserve existing bot functionality as fallback
- Add bundle mode alongside sequential mode
- Implement intelligent mode selection based on conditions
- Maintain consistent logging and monitoring

### CLI Enhancements
- New flags for bundle configuration
- Bundle-specific debugging options
- Performance comparison commands
- Migration assistance tools

## Implementation Steps

### 1. Main Bot Integration (Day 1-2)
```python
# src/arbitrage_commands/pectra_bot.py
class PectraBundleBot:
    def __init__(
        self,
        config: BotConfig,
        bundle_mode: bool = True,
        fallback_enabled: bool = True
    ):
        self.config = config
        self.bundle_mode = bundle_mode
        self.fallback_enabled = fallback_enabled
        
        # Initialize components
        self.price_monitor = PriceMonitor(config)
        self.bundle_builder = BundleBuilder(config)
        self.sequential_executor = SequentialExecutor(config)
        self.simulator = BundleSimulator(config.fork_url)
        
        # Performance tracking
        self.metrics = BotMetrics()
        
    async def run(self):
        """Main arbitrage loop with bundle support"""
        
        logger.info(f"Starting Pectra bot in {'bundle' if self.bundle_mode else 'sequential'} mode")
        
        while True:
            try:
                # 1. Check for arbitrage opportunity
                opportunity = await self.find_opportunity()
                
                if not opportunity:
                    await asyncio.sleep(self.config.interval)
                    continue
                
                # 2. Decide execution mode
                execution_mode = self.select_execution_mode(opportunity)
                
                # 3. Execute arbitrage
                if execution_mode == "bundle":
                    result = await self.execute_bundle(opportunity)
                else:
                    result = await self.execute_sequential(opportunity)
                
                # 4. Record metrics
                self.metrics.record_execution(result)
                
                # 5. Log results
                self.log_execution_result(result)
                
            except Exception as e:
                logger.error(f"Bot error: {e}")
                if not self.fallback_enabled:
                    raise
                    
            await asyncio.sleep(self.config.interval)
    
    def select_execution_mode(
        self,
        opportunity: ArbitrageOpportunity
    ) -> str:
        """Intelligently select bundle vs sequential execution"""
        
        if not self.bundle_mode:
            return "sequential"
        
        # Check bundle viability
        checks = {
            "implementation_deployed": self.check_implementation(),
            "sufficient_profit": opportunity.expected_profit > self.config.min_bundle_profit,
            "gas_price_reasonable": self.check_gas_price() < self.config.max_gas_price,
            "network_compatible": self.check_network_compatibility()
        }
        
        if all(checks.values()):
            return "bundle"
        else:
            logger.info(f"Falling back to sequential: {checks}")
            return "sequential"
    
    async def execute_bundle(
        self,
        opportunity: ArbitrageOpportunity
    ) -> ExecutionResult:
        """Execute arbitrage using bundled transactions"""
        
        start_time = time.time()
        
        try:
            # 1. Build bundle based on opportunity type
            if opportunity.direction == "buy_conditional":
                bundle, metadata = self.bundle_builder.build_buy_bundle(
                    opportunity.amount,
                    opportunity.prices
                )
            else:
                bundle, metadata = self.bundle_builder.build_sell_bundle(
                    opportunity.amount,
                    opportunity.prices
                )
            
            # 2. Simulate bundle
            simulation = await self.simulator.simulate_bundle(
                bundle,
                self.config.account.address,
                self.config.implementation_address
            )
            
            if not simulation.success:
                return ExecutionResult(
                    success=False,
                    reason=f"Simulation failed: {simulation.failure_reason}"
                )
            
            # 3. Verify profitability
            if simulation.profit < self.config.min_profit:
                return ExecutionResult(
                    success=False,
                    reason=f"Unprofitable: {simulation.profit}"
                )
            
            # 4. Execute on-chain
            tx_hash = await self.execute_bundle_onchain(bundle)
            
            # 5. Wait for confirmation
            receipt = await self.wait_for_receipt(tx_hash)
            
            return ExecutionResult(
                success=True,
                tx_hash=tx_hash,
                profit=simulation.profit,
                gas_used=receipt.gasUsed,
                execution_time=time.time() - start_time,
                mode="bundle"
            )
            
        except Exception as e:
            logger.error(f"Bundle execution failed: {e}")
            
            if self.fallback_enabled:
                logger.info("Attempting sequential fallback")
                return await self.execute_sequential(opportunity)
            else:
                return ExecutionResult(
                    success=False,
                    reason=str(e),
                    execution_time=time.time() - start_time
                )
```

### 2. CLI Updates (Day 2-3)
```python
# src/cli/cli.py
@click.command()
@click.option('--amount', type=float, required=True, help='Amount of sDAI to trade')
@click.option('--interval', type=int, default=120, help='Polling interval in seconds')
@click.option('--tolerance', type=float, default=0.04, help='Price tolerance threshold')
@click.option('--bundle/--no-bundle', default=True, help='Enable bundled transactions')
@click.option('--implementation', type=str, help='Implementation contract address')
@click.option('--fallback/--no-fallback', default=True, help='Enable sequential fallback')
@click.option('--simulate-only', is_flag=True, help='Only simulate, don\'t execute')
@click.option('--compare-modes', is_flag=True, help='Compare bundle vs sequential')
@click.option('--gas-limit', type=int, help='Maximum gas for bundle execution')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def pectra_bot(
    amount: float,
    interval: int,
    tolerance: float,
    bundle: bool,
    implementation: Optional[str],
    fallback: bool,
    simulate_only: bool,
    compare_modes: bool,
    gas_limit: Optional[int],
    debug: bool
):
    """Run Pectra arbitrage bot with EIP-7702 bundled transactions"""
    
    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level)
    
    # Load configuration
    config = BotConfig.from_env()
    config.amount = Decimal(str(amount))
    config.interval = interval
    config.tolerance = Decimal(str(tolerance))
    config.bundle_mode = bundle
    config.fallback_enabled = fallback
    
    # Override implementation if provided
    if implementation:
        config.implementation_address = implementation
    
    # Special modes
    if compare_modes:
        run_comparison_mode(config)
        return
    
    if simulate_only:
        run_simulation_mode(config)
        return
    
    # Run main bot
    bot = PectraBundleBot(config)
    asyncio.run(bot.run())

def run_comparison_mode(config: BotConfig):
    """Compare bundle vs sequential execution"""
    
    comparator = ExecutionComparator(config)
    
    print("Running execution comparison mode...")
    print("-" * 50)
    
    # Find opportunity
    opportunity = comparator.find_opportunity()
    if not opportunity:
        print("No arbitrage opportunity found")
        return
    
    # Simulate both modes
    bundle_result = comparator.simulate_bundle(opportunity)
    sequential_result = comparator.simulate_sequential(opportunity)
    
    # Display comparison
    print(f"\nOpportunity: {opportunity}")
    print(f"\nBundle Mode:")
    print(f"  - Success: {bundle_result.success}")
    print(f"  - Profit: {bundle_result.profit}")
    print(f"  - Gas Used: {bundle_result.gas_used}")
    print(f"  - Execution Time: {bundle_result.execution_time}s")
    
    print(f"\nSequential Mode:")
    print(f"  - Success: {sequential_result.success}")
    print(f"  - Profit: {sequential_result.profit}")
    print(f"  - Gas Used: {sequential_result.gas_used}")
    print(f"  - Execution Time: {sequential_result.execution_time}s")
    
    print(f"\nBundle Advantages:")
    print(f"  - Gas Savings: {sequential_result.gas_used - bundle_result.gas_used}")
    print(f"  - Time Savings: {sequential_result.execution_time - bundle_result.execution_time}s")
    print(f"  - MEV Protection: Yes")
```

### 3. Feature Flag System (Day 3-4)
```python
# src/config/feature_flags.py
class FeatureFlags:
    def __init__(self):
        self.flags = {
            "bundle_enabled": self._load_flag("BUNDLE_ENABLED", True),
            "bundle_percentage": self._load_flag("BUNDLE_PERCENTAGE", 100),
            "fallback_enabled": self._load_flag("FALLBACK_ENABLED", True),
            "advanced_liquidation": self._load_flag("ADVANCED_LIQUIDATION", False),
            "gas_optimization": self._load_flag("GAS_OPTIMIZATION", True),
            "tenderly_simulation": self._load_flag("TENDERLY_SIMULATION", False)
        }
        
    def should_use_bundle(self, opportunity: ArbitrageOpportunity) -> bool:
        """Determine if bundle should be used for this opportunity"""
        
        if not self.flags["bundle_enabled"]:
            return False
        
        # Gradual rollout based on percentage
        if random.randint(1, 100) > self.flags["bundle_percentage"]:
            return False
        
        # Check opportunity-specific criteria
        if opportunity.complexity > 5 and not self.flags["advanced_liquidation"]:
            return False
        
        return True
    
    def update_flag(self, name: str, value: Any):
        """Update feature flag dynamically"""
        self.flags[name] = value
        logger.info(f"Updated feature flag {name} to {value}")

# Integration with bot
class PectraBundleBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.feature_flags = FeatureFlags()
        
    def select_execution_mode(self, opportunity: ArbitrageOpportunity) -> str:
        if self.feature_flags.should_use_bundle(opportunity):
            return "bundle"
        else:
            return "sequential"
```

### 4. Migration Utilities (Day 4)
```python
# src/migration/bundle_migrator.py
class BundleMigrator:
    def __init__(self, config: BotConfig):
        self.config = config
        self.validator = MigrationValidator()
        
    def validate_migration_readiness(self) -> MigrationReport:
        """Check if system is ready for bundle migration"""
        
        report = MigrationReport()
        
        # Check implementation contract
        report.add_check(
            "implementation_deployed",
            self.check_implementation_deployment()
        )
        
        # Verify environment variables
        report.add_check(
            "environment_configured",
            self.check_environment_config()
        )
        
        # Test bundle building
        report.add_check(
            "bundle_building_works",
            self.test_bundle_building()
        )
        
        # Verify gas estimation
        report.add_check(
            "gas_estimation_accurate",
            self.test_gas_estimation()
        )
        
        return report
    
    def create_migration_plan(self) -> MigrationPlan:
        """Create step-by-step migration plan"""
        
        plan = MigrationPlan()
        
        # Phase 1: Testing
        plan.add_phase("testing", [
            "Deploy implementation to testnet",
            "Run parallel testing for 24 hours",
            "Verify gas savings and profitability",
            "Fix any issues found"
        ])
        
        # Phase 2: Gradual Rollout
        plan.add_phase("rollout", [
            "Enable bundle mode for 10% of trades",
            "Monitor for 48 hours",
            "Increase to 50% if stable",
            "Full rollout after 1 week"
        ])
        
        # Phase 3: Optimization
        plan.add_phase("optimization", [
            "Analyze gas usage patterns",
            "Implement suggested optimizations",
            "Remove sequential fallback if stable"
        ])
        
        return plan

# CLI command for migration
@click.command()
@click.option('--check', is_flag=True, help='Check migration readiness')
@click.option('--plan', is_flag=True, help='Generate migration plan')
@click.option('--execute', is_flag=True, help='Execute migration')
def migrate_to_bundle(check: bool, plan: bool, execute: bool):
    """Migrate bot to bundled transaction mode"""
    
    migrator = BundleMigrator(BotConfig.from_env())
    
    if check:
        report = migrator.validate_migration_readiness()
        print(report.format())
        
    if plan:
        migration_plan = migrator.create_migration_plan()
        print(migration_plan.format())
        
    if execute:
        if not click.confirm("Start migration to bundle mode?"):
            return
        migrator.execute_migration()
```

### 5. Monitoring Integration (Day 5)
```python
# src/monitoring/bundle_metrics.py
class BundleMetrics:
    def __init__(self):
        self.executions = []
        self.comparisons = []
        
    def record_execution(self, result: ExecutionResult):
        """Record execution metrics"""
        
        self.executions.append({
            "timestamp": time.time(),
            "mode": result.mode,
            "success": result.success,
            "profit": float(result.profit) if result.profit else 0,
            "gas_used": result.gas_used,
            "execution_time": result.execution_time
        })
        
        # Send to monitoring service
        self.send_to_prometheus(result)
        
    def send_to_prometheus(self, result: ExecutionResult):
        """Send metrics to Prometheus"""
        
        # Success rate
        success_gauge.labels(mode=result.mode).set(
            1 if result.success else 0
        )
        
        # Profit tracking
        if result.profit:
            profit_histogram.labels(mode=result.mode).observe(
                float(result.profit)
            )
        
        # Gas usage
        if result.gas_used:
            gas_histogram.labels(mode=result.mode).observe(
                result.gas_used
            )
        
        # Execution time
        execution_time_histogram.labels(mode=result.mode).observe(
            result.execution_time
        )
    
    def generate_comparison_report(self) -> Dict[str, Any]:
        """Generate bundle vs sequential comparison report"""
        
        bundle_executions = [e for e in self.executions if e["mode"] == "bundle"]
        sequential_executions = [e for e in self.executions if e["mode"] == "sequential"]
        
        if not bundle_executions or not sequential_executions:
            return {"error": "Insufficient data for comparison"}
        
        return {
            "bundle": {
                "count": len(bundle_executions),
                "success_rate": sum(1 for e in bundle_executions if e["success"]) / len(bundle_executions),
                "avg_profit": sum(e["profit"] for e in bundle_executions) / len(bundle_executions),
                "avg_gas": sum(e["gas_used"] for e in bundle_executions if e["gas_used"]) / len(bundle_executions),
                "avg_time": sum(e["execution_time"] for e in bundle_executions) / len(bundle_executions)
            },
            "sequential": {
                "count": len(sequential_executions),
                "success_rate": sum(1 for e in sequential_executions if e["success"]) / len(sequential_executions),
                "avg_profit": sum(e["profit"] for e in sequential_executions) / len(sequential_executions),
                "avg_gas": sum(e["gas_used"] for e in sequential_executions if e["gas_used"]) / len(sequential_executions),
                "avg_time": sum(e["execution_time"] for e in sequential_executions) / len(sequential_executions)
            },
            "improvements": {
                "gas_savings": f"{(1 - bundle_stats['avg_gas'] / sequential_stats['avg_gas']) * 100:.2f}%",
                "time_reduction": f"{(1 - bundle_stats['avg_time'] / sequential_stats['avg_time']) * 100:.2f}%"
            }
        }
```

## Testing Approach

### Integration Tests
1. **Bot Loop Testing**: Test main arbitrage loop with bundles
2. **Mode Selection**: Verify correct mode selection logic
3. **Fallback Testing**: Ensure fallback works correctly
4. **CLI Testing**: Test all new CLI commands

### Migration Tests
1. **Readiness Checks**: Verify migration validation
2. **Gradual Rollout**: Test percentage-based routing
3. **Rollback Testing**: Ensure clean rollback capability
4. **Data Migration**: Test historical data compatibility

### Monitoring Tests
1. **Metrics Collection**: Verify all metrics captured
2. **Alert Testing**: Test alerting thresholds
3. **Dashboard Updates**: Ensure dashboards show bundle data
4. **Performance Tracking**: Validate comparison reports

## Success Criteria

### Integration Success
- [ ] Seamless operation in both modes
- [ ] No degradation in sequential mode
- [ ] Proper fallback behavior
- [ ] All CLI commands functional

### Migration Success
- [ ] Zero-downtime migration
- [ ] Gradual rollout working
- [ ] Rollback capability verified
- [ ] Documentation complete

### Monitoring Success
- [ ] All metrics visible in dashboards
- [ ] Alerts configured and tested
- [ ] Performance comparisons accurate
- [ ] Historical data preserved

## Risk Mitigation

### Integration Risks
1. **Breaking Changes**
   - Mitigation: Extensive backward compatibility testing
   - Feature flags for gradual rollout
   - Comprehensive fallback mechanisms

2. **Performance Regression**
   - Mitigation: Continuous performance monitoring
   - A/B testing between modes
   - Quick rollback capability

3. **Configuration Complexity**
   - Mitigation: Sensible defaults
   - Configuration validation
   - Clear documentation

### Operational Risks
1. **Migration Failures**
   - Mitigation: Staged rollout plan
   - Rollback procedures
   - Backup strategies

2. **Monitoring Gaps**
   - Mitigation: Comprehensive metric coverage
   - Multiple monitoring systems
   - Manual verification procedures

## Dependencies
- All previous subtasks completed
- Monitoring infrastructure ready
- Documentation updated
- Team training completed

## Deliverables
1. Fully integrated pectra_bot.py
2. Enhanced CLI with bundle support
3. Feature flag system
4. Migration utilities and guides
5. Monitoring dashboards
6. Performance comparison reports
7. User documentation