from dataclasses import dataclass
from datetime import datetime
import argparse
import subprocess
import sys
from typing import Optional, List
import dateutil.parser
from rich.console import Console
from rich.table import Table
from pathlib import Path
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

@dataclass
class DomainInfo:
    """
    Data class to hold domain information.
    
    Attributes:
        name (str): The domain name being checked
        expiry_date (Optional[datetime]): When the domain registration expires
        registrar (str): The domain registrar name
        days_remaining (Optional[int]): Number of days until expiration
        status (str): Status of the domain check:
            - 'active': Domain is registered and active
            - 'available': Domain appears to be available for registration
            - 'error': Technical error occurred during check
            - 'rate_limited': WHOIS server rate limit exceeded
            - 'connection_failed': Network or connection issue
            - 'unknown': Couldn't determine status
        error_message (Optional[str]): Detailed error or status message
    """
    name: str
    expiry_date: Optional[datetime]
    registrar: str
    days_remaining: Optional[int]
    status: str = 'active'
    error_message: Optional[str] = None

    @property
    def formatted_date(self) -> str:
        """Returns the expiry date formatted in UK style (DD/MM/YYYY) or status message."""
        if self.expiry_date:
            return self.expiry_date.strftime("%d/%m/%Y")
        
        status_messages = {
            'available': "Available for registration",
            'error': "Check failed - Technical error",
            'rate_limited': "Check failed - Rate limited",
            'connection_failed': "Check failed - Connection error",
            'unknown': "Status unknown"
        }
        return status_messages.get(self.status, "Status unknown")

    def get_error_message(self, debug: bool = False) -> str:
        """Returns error message, shortened version if not in debug mode."""
        if not self.error_message:
            return ""

        if not debug:
            # Shortened messages for normal mode
            if "WHOIS command failed" in self.error_message:
                return "WHOIS query failed"
            if "command not found" in self.error_message:
                return "WHOIS not installed"
            if "Rate limit" in self.error_message or "LIMIT EXCEEDED" in self.error_message:
                return "Rate limited"
            if any(err in self.error_message for err in ["CONNECTION", "TIMEOUT", "NETWORK"]):
                return "Connection error"
            return self.error_message.split('\n')[0]  # Just first line for other errors

        return self.error_message  # Full message in debug mode

class DomainChecker:
    """
    Handles domain checking operations including WHOIS queries and data parsing.
    """
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.console = Console(stderr=True) if debug else None

    EXPIRE_STRINGS = [
        "Registry Expiry Date:",
        "Expiration:",
        "Domain Expiration Date",
        "Registrar Registration Expiration Date:",
        "expire:",
        "expires:",
        "Expiry date"
    ]
    REGISTRAR_STRINGS = ["Registrar:"]

    def get_domain_info(self, domain: str) -> Optional[DomainInfo]:
        """
        Retrieve and process information for a single domain.
        """
        if self.debug:
            self.console.print(f"\n[bold blue]DEBUG:[/bold blue] Processing domain: {domain}")
        
        try:
            whois_data = self._execute_whois(domain)
            if not whois_data:
                if self.debug:
                    self.console.print(f"[bold red]DEBUG:[/bold red] WHOIS query failed for {domain}")
                return DomainInfo(
                    name=domain,
                    expiry_date=None,
                    registrar="Unknown",
                    days_remaining=None,
                    status='error',
                    error_message="WHOIS query failed"
                )
            
            if self.debug:
                self.console.print(f"[bold green]DEBUG:[/bold green] Got WHOIS response for {domain} ({len(whois_data)} bytes)")
                
            expiry_date, registrar, error_message, status = self._parse_whois_data(whois_data)
            days_remaining = (expiry_date - datetime.now()).days if expiry_date else None
            
            if self.debug:
                self.console.print(f"[bold yellow]DEBUG:[/bold yellow] Parsed data for {domain}:")
                self.console.print(f"  - Expiry date: {expiry_date}")
                self.console.print(f"  - Registrar: {registrar}")
                self.console.print(f"  - Days remaining: {days_remaining}")
                self.console.print(f"  - Error message: {error_message}")
                self.console.print(f"  - Status: {status}")
            
            return DomainInfo(
                name=domain,
                expiry_date=expiry_date,
                registrar=registrar,
                days_remaining=days_remaining,
                status=status,
                error_message=error_message
            )
        except Exception as e:
            if self.debug:
                self.console.print(f"[bold red]DEBUG:[/bold red] Error processing {domain}: {str(e)}")
            return DomainInfo(
                name=domain,
                expiry_date=None,
                registrar="Unknown",
                days_remaining=None,
                status='error',
                error_message=str(e)
            )

    def _execute_whois(self, domain: str) -> Optional[str]:
        """
        Execute WHOIS query for the given domain.
        """
        try:
            if self.debug:
                self.console.print(f"[blue]Executing command:[/blue] whois {domain}")
            
            process = subprocess.run(
                ['whois', domain],
                capture_output=True,
                text=True,
                check=False  # Don't raise exception, we'll handle it
            )
            
            # Process completed and has output
            if process.stdout.strip():
                if self.debug:
                    self.console.print("[green]WHOIS query successful[/green]")
                return process.stdout
            
            # No output at all is an error
            error_msg = "WHOIS command returned empty response"
            if self.debug:
                self.console.print(f"[red]Error:[/red] {error_msg}")
            raise Exception(error_msg)
            
        except FileNotFoundError:
            error_msg = (
                "WHOIS command not found. Please install whois:\n"
                "- On Ubuntu/Debian: sudo apt-get install whois\n"
                "- On CentOS/RHEL: sudo yum install whois\n"
                "- On macOS: brew install whois"
            )
            if self.debug:
                self.console.print(f"[red]Error:[/red] {error_msg}")
            raise Exception(error_msg)
            
        except Exception as e:
            # Handle any other unexpected errors
            error_msg = f"Unexpected error executing WHOIS command: {str(e)}"
            if self.debug:
                self.console.print(f"[red]Error:[/red] {error_msg}")
            raise Exception(error_msg)

    def _parse_whois_data(self, whois_data: str) -> tuple[Optional[datetime], str, Optional[str], str]:
        """
        Parse WHOIS data to extract expiry date, registrar, and detailed status information.
        """
        expiry_date = None
        registrar = "Unknown"
        error_message = None
        status = 'unknown'
        whois_upper = whois_data.upper()

        # Check for domain availability first - this is not an error state
        if "NO MATCH FOR DOMAIN" in whois_upper:
            return None, "Available", "Domain is available for registration", 'available'

        # Other common availability indicators
        availability_patterns = [
            "NOT FOUND",
            "NO ENTRIES FOUND",
            "DOMAIN NOT FOUND",
            "STATUS: AVAILABLE",
            "DOMAIN STATUS: FREE",
            "DOMAIN NOT REGISTERED"
        ]
        if any(pattern in whois_upper for pattern in availability_patterns):
            return None, "Available", "Domain appears to be available", 'available'

        # Only check for errors if we haven't determined it's available
        rate_limit_patterns = {
            "WHOIS LIMIT EXCEEDED": "Rate limit reached",
            "TOO MANY REQUESTS": "Server is throttling requests",
            "QUERY RATE EXCEEDED": "Too many queries",
            "QUOTA EXCEEDED": "Query quota exceeded"
        }
        for pattern, message in rate_limit_patterns.items():
            if pattern in whois_upper:
                return None, "Unknown", message, 'rate_limited'

        connection_error_patterns = {
            "CONNECTION REFUSED": "Server connection refused",
            "TIMEOUT": "Connection timed out",
            "CONNECTION RESET": "Connection was reset",
            "NETWORK ERROR": "Network error occurred",
            "SERVER ERROR": "Server error"
        }
        for pattern, message in connection_error_patterns.items():
            if pattern in whois_upper:
                return None, "Unknown", message, 'connection_failed'

        # If we get here, try to parse registration details
        for line in whois_data.splitlines():
            if not expiry_date:
                for expire_string in self.EXPIRE_STRINGS:
                    if expire_string in line:
                        try:
                            date_str = line.split(expire_string)[1].strip()
                            expiry_date = dateutil.parser.parse(date_str, ignoretz=True)
                            break
                        except (ValueError, IndexError):
                            continue

            for registrar_string in self.REGISTRAR_STRINGS:
                if registrar_string in line:
                    registrar = line.split(registrar_string)[1].strip()
                    break

        # Set final status
        if expiry_date:
            status = 'active'
            remaining_days = (expiry_date - datetime.now()).days
            if remaining_days < 0:
                error_message = "Expired"
            elif remaining_days < 30:
                error_message = f"{remaining_days} days left"
        else:
            # If we get here with no expiry date and no previous status,
            # the domain might still be available
            if "Domain Name:" in whois_data and registrar == "Unknown":
                status = 'available'
                error_message = "No registration data found"

        return expiry_date, registrar, error_message, status

class ConsoleOutput:
    """
    Handles console output formatting using the Rich library and CSV export.
    """
    
    def __init__(self, debug: bool = False):
        self.console = Console()
        self.debug = debug

    def display_results(self, domains: List[DomainInfo]) -> None:
        """
        Display domain information in a formatted table and optionally save to CSV.
        """
        table = Table(show_header=True, header_style="bold")
        table.add_column("Domain Name", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Expiry Date", style="green")
        table.add_column("Days Left", justify="right")
        table.add_column("Registrar", style="yellow")
        table.add_column("Details", style="white")

        # Sort domains: errors first, then by status and days remaining
        def sort_key(domain):
            status_order = {
                'rate_limited': 0,
                'connection_failed': 1,
                'error': 2,
                'available': 3,
                'active': 4,
                'unknown': 5
            }
            if domain.status == 'active':
                return (status_order[domain.status], 
                       domain.days_remaining if domain.days_remaining is not None else float('inf'))
            return (status_order.get(domain.status, 6), float('inf'))

        sorted_domains = sorted(domains, key=sort_key)

        for domain in sorted_domains:
            status_style = {
                'active': 'green',
                'available': 'yellow',
                'rate_limited': 'red bold',
                'connection_failed': 'red',
                'error': 'red',
                'unknown': 'white'
            }.get(domain.status, 'white')

            status_display = {
                'active': 'Active',
                'available': 'Available',
                'rate_limited': 'Rate Limited',
                'connection_failed': 'Conn Failed',
                'error': 'Error',
                'unknown': 'Unknown'
            }.get(domain.status, domain.status.title())

            days_style = "red" if domain.days_remaining and domain.days_remaining < 30 else "green"
            
            table.add_row(
                domain.name,
                f"[{status_style}]{status_display}[/{status_style}]",
                domain.formatted_date,
                "[grey]N/A[/grey]" if domain.days_remaining is None else f"[{days_style}]{domain.days_remaining}[/{days_style}]",
                domain.registrar if domain.registrar != "Unknown" else "[grey]Unknown[/grey]",
                domain.get_error_message(debug=self.debug)
            )
        
        self.console.print(table)

    def save_to_csv(self, domains: List[DomainInfo], filepath: str) -> None:
        """
        Save domain information to a CSV file.
        """
        import csv
        from datetime import datetime

        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                'Domain Name',
                'Status',
                'Expiry Date',
                'Days Remaining',
                'Registrar',
                'Details',
                'Check Date'
            ])
            
            check_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for domain in domains:
                writer.writerow([
                    domain.name,
                    domain.status,
                    domain.formatted_date,
                    domain.days_remaining if domain.days_remaining is not None else 'N/A',
                    domain.registrar,
                    domain.get_error_message(debug=self.debug),
                    check_date
                ])

def main():
    """
    Main entry point for the domain expiration checker.
    """
    parser = argparse.ArgumentParser(description='Domain Expiration Checker')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-d', '--domain', help="Single domain to check")
    group.add_argument('-f', '--file', type=Path, help="File containing list of domains (one per line)")
    parser.add_argument('--parallel', action='store_true', help="Process domains in parallel")
    parser.add_argument('--csv', help="Save results to CSV file")
    parser.add_argument('--debug', action='store_true', help="Enable debug output")
    
    args = parser.parse_args()
    
    checker = DomainChecker(debug=args.debug)
    output = ConsoleOutput(debug=args.debug)
    domains_to_check = []

    if args.domain:
        domains_to_check = [args.domain]
    else:
        try:
            with open(args.file) as f:
                domains_to_check = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"Error reading domain file: {str(e)}", file=sys.stderr)
            sys.exit(1)

    start_time = time.time()
    results = []

    if args.parallel and len(domains_to_check) > 1:
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=min(len(domains_to_check), 10)) as executor:
            future_to_domain = {executor.submit(checker.get_domain_info, domain): domain 
                              for domain in domains_to_check}
            for future in concurrent.futures.as_completed(future_to_domain):
                if info := future.result():
                    results.append(info)
    else:
        # Sequential processing
        for domain in domains_to_check:
            if info := checker.get_domain_info(domain):
                results.append(info)
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    
    if results:
        output.display_results(results)
        if args.csv:
            try:
                output.save_to_csv(results, args.csv)
                print(f"\nResults saved to: {args.csv}")
            except Exception as e:
                print(f"Error saving to CSV: {str(e)}", file=sys.stderr)
        print(f"\nTime taken: {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    main()
